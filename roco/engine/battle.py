"""Turn-based battle engine — two-tier data model with pkmn-style bitfields."""

from __future__ import annotations

from roco.engine.damage import energy_after_gain, can_use_skill
from roco.engine.state import (
    ActivePokemon, PersistentPokemon, SkillData, SkillCategory,
    BattleEvent as BEvent, MoveDecision, BattleState,
    StatusFlag, StatusType, WeatherType, Stats,
    _unpack_buff, _set_buff, _pack_buff,
    _unpack_status, _set_status,
    _pack_cooldown, _unpack_cooldown,
    _pack_weather,
)
from roco.engine.events import EventBus, EventCtx, GameEvent
from roco.config.constants import STARTING_ENERGY, DEFAULT_MAX_TURNS
from roco.systems.marks import apply_marks_to_speed, apply_marks_to_skill_cost
from roco.systems.counter import resolve_counter


class BattleEngine:
    def __init__(self, team_a: list[PersistentPokemon], team_b: list[PersistentPokemon],
                 max_turns: int = DEFAULT_MAX_TURNS):
        self.max_turns = max_turns
        if not team_a or not team_b:
            raise ValueError("Both teams must have at least 1 pet")

        act_a = [ActivePokemon(p) for p in team_a]
        act_b = [ActivePokemon(p) for p in team_b]
        for i, pet in enumerate(act_a + act_b):
            pet.current_hp = pet.max_hp
            pet.current_energy = STARTING_ENERGY
            pet.slot = i % 6
        self.state = BattleState(team_a=act_a, team_b=act_b)

        self.bus = EventBus()
        self._init_systems()
        self._register_engine_handlers()

        for pet in act_a + act_b:
            from roco.engine.ability import register_ability_handlers
            register_ability_handlers(self.bus, pet)

        self.bus.emit(EventCtx(GameEvent.BATTLE_START, self.state))
        for pet in act_a + act_b:
            self.bus.emit(EventCtx(GameEvent.PASSIVE, self.state, actor=pet))
        for team, pet in (("a", act_a[0]), ("b", act_b[0])):
            self.bus.emit(EventCtx(GameEvent.SWITCH_IN, self.state, actor=pet, data={"team": team}))

    def _init_systems(self):
        import importlib
        for mod_name, fn_name in [
            ("roco.systems.weather", "register_weather_handlers"),
            ("roco.systems.marks", "register_mark_handlers"),
            ("roco.engine.skill_exec", "register_skill_handlers"),
            ("roco.systems.burst", "register_burst_handlers"),
            ("roco.systems.barrel", "register_barrel_handlers"),
            ("roco.systems.devotion", "register_devotion_handlers"),
            ("roco.systems.cute", "register_cute_handlers"),
        ]:
            mod = importlib.import_module(mod_name)
            getattr(mod, fn_name)(self.bus)

    def _register_engine_handlers(self):
        self.bus.on(GameEvent.FAINT, self._on_faint, priority=999, source="engine")
        self.bus.on(GameEvent.TURN_END, self._on_turn_end_status, priority=300, source="engine")

    def _on_faint(self, ctx: EventCtx):
        pet = ctx.actor
        if not pet: return
        is_a = pet in self.state.team_a
        cost = 0 if "fake_death" in pet.persistent.ability_tags else 1
        if is_a: self.state.magic_a = max(0, self.state.magic_a - cost)
        else: self.state.magic_b = max(0, self.state.magic_b - cost)
        self.state.log.append(BEvent(turn=self.state.turn_number, actor=pet.persistent.name, action="faint",
            detail={"magic_cost": cost, "magic_remaining": self.state.magic_a if is_a else self.state.magic_b}))

    def _on_turn_end_status(self, ctx: EventCtx):
        from roco.engine.damage import calc_burn_damage, burn_decay, calc_poison_damage, get_type_multiplier
        for pet in self.state.team_a + self.state.team_b:
            if pet.is_fainted: continue
            if pet.has_status(StatusFlag.BURN):
                s = pet.get_status_count(StatusType.BURN)
                dmg = calc_burn_damage(pet.max_hp, s, get_type_multiplier("火", pet.elements), mid_turn=False)
                pet.current_hp = max(0, pet.current_hp - dmg)
                pet.set_status_count(StatusType.BURN, burn_decay(s))
                self.state.log.append(BEvent(turn=self.state.turn_number, actor=pet.persistent.name, action="status_tick",
                    detail={"status":"灼烧","damage":dmg,"stacks_before":s}))
            if pet.has_status(StatusFlag.POISON):
                s = pet.get_status_count(StatusType.POISON)
                dmg = calc_poison_damage(pet.max_hp, s)
                pet.current_hp = max(0, pet.current_hp - dmg)
                self.state.log.append(BEvent(turn=self.state.turn_number, actor=pet.persistent.name, action="status_tick",
                    detail={"status":"中毒","damage":dmg}))
            if pet.current_hp <= 0:
                self._handle_faint(pet)

    # ── Public API ──────────────────────────────────────────────

    def step(self, move_a: MoveDecision, move_b: MoveDecision) -> BattleState:
        s = self.state; s.turn_number += 1
        self.bus.emit(EventCtx(GameEvent.TURN_START, s))

        for team in (s.team_a, s.team_b):
            for pet in team:
                if not pet.is_fainted:
                    pet.current_energy = energy_after_gain(pet.current_energy)

        a_pet, b_pet = s.team_a[s.active_a], s.team_b[s.active_b]
        a_spd = apply_marks_to_speed(a_pet.speed, s.marks_a)
        b_spd = apply_marks_to_speed(b_pet.speed, s.marks_b)
        a_first = a_spd >= b_spd

        a_cat, b_cat = self._cat(a_pet, move_a), self._cat(b_pet, move_b)
        a_ctr, b_ctr = resolve_counter(a_cat, b_cat)
        if a_ctr: self.bus.emit(EventCtx(GameEvent.COUNTER_SUCCESS, s, actor=a_pet, target=b_pet))
        if b_ctr: self.bus.emit(EventCtx(GameEvent.COUNTER_SUCCESS, s, actor=b_pet, target=a_pet))

        f_pet = a_pet if a_first else b_pet; s_pet = b_pet if a_first else a_pet
        f_mv = move_a if a_first else move_b; s_mv = move_b if a_first else move_a
        f_team = "a" if a_first else "b"; s_team = "b" if a_first else "a"
        c1 = (f_team=="a" and b_ctr) or (f_team=="b" and a_ctr)
        self._exec(f_pet, s_pet, f_mv, f_team, s, c1)
        if not s_pet.is_fainted:
            c2 = (s_team=="a" and b_ctr) or (s_team=="b" and a_ctr)
            self._exec(s_pet, f_pet, s_mv, s_team, s, c2)

        self.bus.emit(EventCtx(GameEvent.TURN_END, s))
        self._check_win(s)
        return s

    def is_finished(self): return self.state.winner is not None
    def get_winner(self): return self.state.winner

    def get_active(self, team: str) -> ActivePokemon:
        idx = self.state.active_a if team == "a" else self.state.active_b
        return (self.state.team_a if team == "a" else self.state.team_b)[idx]

    def get_available_switches(self, team: str) -> list[int]:
        pets = self.state.team_a if team == "a" else self.state.team_b
        active = self.state.active_a if team == "a" else self.state.active_b
        return [i for i, p in enumerate(pets) if i != active and not p.is_fainted]

    def get_valid_moves(self, team: str) -> list[int]:
        pet = self.get_active(team)
        if pet.charging_skill >= 0: return [pet.charging_skill]
        marks = self.state.marks_a if team == "a" else self.state.marks_b
        return [i for i, m in enumerate(pet.persistent.moves)
                if can_use_skill(pet.current_energy, apply_marks_to_skill_cost(m.energy, marks))
                and (_unpack_cooldown(pet.cooldowns).get(i, 0) <= 0)]

    # ── Internal ────────────────────────────────────────────────

    def _cat(self, pet: ActivePokemon, d: MoveDecision) -> SkillCategory:
        if d.action != "move" or d.skill_index is None: return SkillCategory.PHYSICAL
        idx = d.skill_index
        if idx < 0 or idx >= len(pet.persistent.moves): return SkillCategory.PHYSICAL
        return pet.persistent.moves[idx].category

    def _exec(self, actor: ActivePokemon, target: ActivePokemon, d: MoveDecision, team: str,
              state: BattleState, countered: bool):
        if actor.is_fainted: return
        if d.action == "switch":
            self._do_switch(actor, d, team, state)
        elif d.action == "move" and d.skill_index is not None:
            ctx = EventCtx(GameEvent.BEFORE_MOVE, state, actor=actor, target=target,
                           data={"team":team, "countered":countered, "skill_index":d.skill_index})
            self.bus.emit(ctx)
            if ctx.cancelled: return
            from roco.engine.skill_exec import execute_move
            hp_before = target.current_hp
            execute_move(actor, target, d.skill_index, state, countered)
            dmg = hp_before - target.current_hp
            if dmg > 0:
                sk = actor.persistent.moves[d.skill_index] if d.skill_index < len(actor.persistent.moves) else None
                self.bus.emit(EventCtx(GameEvent.AFTER_DAMAGE, state, actor=actor, target=target,
                    data={"damage":dmg, "skill":sk}))
                self.bus.emit(EventCtx(GameEvent.AFTER_MOVE, state, actor=actor, target=target,
                    data={"skill":sk, "damage":dmg}))
            if target.current_hp <= 0:
                self._handle_faint(target)

    def _do_switch(self, switcher: ActivePokemon, d: MoveDecision, team: str, state: BattleState):
        pets = state.team_a if team == "a" else state.team_b
        if d.switch_slot is None: return
        new_idx = d.switch_slot
        if new_idx < 0 or new_idx >= len(pets): return
        new_pet = pets[new_idx]
        if new_pet.is_fainted: return

        self.bus.emit(EventCtx(GameEvent.SWITCH_OUT, state, actor=switcher, data={"team":team}))
        opp_team = "b" if team == "a" else "a"
        opp_active = state.team_b[state.active_b] if team == "a" else state.team_a[state.active_a]
        self.bus.emit(EventCtx(GameEvent.ENEMY_SWITCH, state, actor=opp_active, data={"team":opp_team}))

        switcher.reset_volatile()
        switcher.charging_skill = -1
        switcher._defense_reduction = 0

        state.log.append(BEvent(turn=state.turn_number, actor=switcher.persistent.name, action="switch",
            detail={"from":switcher.persistent.name, "to":new_pet.persistent.name}))

        if team == "a": state.active_a = new_idx
        else: state.active_b = new_idx

        new_pet.current_energy = max(0, new_pet.current_energy)
        self.bus.emit(EventCtx(GameEvent.SWITCH_IN, state, actor=new_pet, data={"team":team}))

    def _handle_faint(self, pet: ActivePokemon):
        pet.is_fainted = True; pet.current_hp = 0
        self.bus.emit(EventCtx(GameEvent.FAINT, self.state, actor=pet))

        # Find killer
        killer = None
        for ev in reversed(self.state.log):
            if ev.action == "attack" and ev.detail.get("target") == pet.persistent.name:
                opp_team = self.state.team_b if pet in self.state.team_a else self.state.team_a
                for opp in opp_team:
                    if opp.persistent.name == ev.actor:
                        killer = opp; break
                break
        if killer:
            self.bus.emit(EventCtx(GameEvent.KILL, self.state, actor=killer, target=pet))
        self.bus.emit(EventCtx(GameEvent.BE_KILLED, self.state, actor=pet, target=killer))

        # Auto-switch
        team = self.state.team_a if pet in self.state.team_a else self.state.team_b
        is_a = team is self.state.team_a
        active_idx = self.state.active_a if is_a else self.state.active_b
        idx = team.index(pet) if pet in team else -1
        if idx != active_idx: return

        for i, p in enumerate(team):
            if i != active_idx and not p.is_fainted:
                if is_a: self.state.active_a = i
                else: self.state.active_b = i
                self.state.log.append(BEvent(turn=self.state.turn_number, actor=p.persistent.name,
                    action="switch", detail={"auto":True,"reason":"faint_replace"}))
                self.bus.emit(EventCtx(GameEvent.SWITCH_IN, self.state, actor=p,
                    data={"team":"a" if is_a else "b"}))
                return

    def _check_win(self, state: BattleState):
        if state.magic_a <= 0 or all(p.is_fainted for p in state.team_a):
            state.winner = "b"
        elif state.magic_b <= 0 or all(p.is_fainted for p in state.team_b):
            state.winner = "a"
        elif state.turn_number >= self.max_turns:
            state.winner = "draw"
