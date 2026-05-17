"""Turn-based battle engine — two-tier data model with engine-style bitfields."""

from __future__ import annotations

import random

from roco.engine.damage import energy_after_gain, can_use_skill
from roco.engine.state import (
    ActivePet, PersistentPet, SkillData, SkillCategory,
    BattleEvent as BEvent, MoveDecision, BattleState,
    StatusFlag, StatusType, AbilityFlag,
    _cooldown_at, _tick_cooldowns,
    record_event,
)
from roco.engine.events import EventBus, EventCtx, GameEvent
from roco.config.constants import STARTING_ENERGY, DEFAULT_MAX_TURNS
from roco.systems.marks import apply_marks_to_speed, apply_marks_to_skill_cost
from roco.systems.counter import resolve_counter


class BattleEngine:
    def __init__(self, team_a: list[PersistentPet], team_b: list[PersistentPet],
                 max_turns: int = DEFAULT_MAX_TURNS, rng_seed: int | None = 0):
        self.max_turns = max_turns
        self.rng = random.Random(rng_seed)
        if not team_a or not team_b:
            raise ValueError("Both teams must have at least 1 pet")

        act_a = [ActivePet(p) for p in team_a]
        act_b = [ActivePet(p) for p in team_b]
        for i, pet in enumerate(act_a + act_b):
            pet.current_hp = pet.max_hp
            pet.current_energy = STARTING_ENERGY
            pet.slot = i % 6
        self.state = BattleState(team_a=act_a, team_b=act_b)

        self.bus = EventBus()
        self._init_systems()
        self._register_engine_stage_hooks()

        for pet in act_a + act_b:
            from roco.engine.ability import register_ability_stage_hooks
            register_ability_stage_hooks(self.bus, pet)

        self.bus.emit(EventCtx(GameEvent.BATTLE_START, self.state))
        for pet in act_a + act_b:
            self.bus.emit(EventCtx(GameEvent.PASSIVE, self.state, actor=pet))
        for team, pet in (("a", act_a[0]), ("b", act_b[0])):
            self.bus.emit(EventCtx(GameEvent.SWITCH_IN, self.state, actor=pet, team=team))

    def _init_systems(self):
        import importlib
        for mod_name, fn_name in [
            ("roco.systems.weather", "register_weather_stage_hooks"),
            ("roco.systems.marks", "register_mark_stage_hooks"),
            ("roco.engine.skill_exec", "register_skill_stage_hooks"),
            ("roco.systems.burst", "register_burst_stage_hooks"),
            ("roco.systems.barrel", "register_barrel_stage_hooks"),
            ("roco.systems.devotion", "register_devotion_stage_hooks"),
            ("roco.systems.cute", "register_cute_stage_hooks"),
        ]:
            mod = importlib.import_module(mod_name)
            getattr(mod, fn_name)(self.bus)

    def _register_engine_stage_hooks(self):
        self.bus.on(GameEvent.FAINT, self._on_faint, priority=999, source="engine")
        self.bus.on(GameEvent.TURN_END, self._on_turn_end_status, priority=300, source="engine")

    def _on_faint(self, ctx: EventCtx):
        pet = ctx.actor
        if not pet: return
        is_a = pet in self.state.team_a
        cost = 0 if (
            pet.has_ability_flag(AbilityFlag.FAKE_DEATH)
            or "fake_death" in pet.persistent.ability_tags
        ) else 1
        if is_a: self.state.magic_a = max(0, self.state.magic_a - cost)
        else: self.state.magic_b = max(0, self.state.magic_b - cost)
        record_event(self.state, BEvent(turn=self.state.turn_number, actor=pet.persistent.name, action="faint",
            detail={"magic_cost": cost, "magic_remaining": self.state.magic_a if is_a else self.state.magic_b}))

    def _on_turn_end_status(self, ctx: EventCtx):
        from roco.engine.damage import calc_burn_damage, burn_decay, calc_poison_damage, get_type_multiplier
        active_pairs = (
            (self.state.team_a[self.state.active_a], self.state.team_b[self.state.active_b]),
            (self.state.team_b[self.state.active_b], self.state.team_a[self.state.active_a]),
        )
        for pet, enemy in active_pairs:
            if pet.is_fainted: continue
            if pet.has_status(StatusFlag.BURN):
                s = pet.get_status_count(StatusType.BURN)
                dmg = calc_burn_damage(pet.max_hp, s, get_type_multiplier("火", pet.elements), mid_turn=False)
                pet.current_hp = max(0, pet.current_hp - dmg)
                if enemy.has_ability_flag(AbilityFlag.BURN_NO_DECAY):
                    pet.set_status_count(StatusType.BURN, s + max(1, s // 2))
                else:
                    pet.set_status_count(StatusType.BURN, burn_decay(s))
                if pet.get_status_count(StatusType.BURN) <= 0:
                    pet.status_flags &= ~StatusFlag.BURN
                record_event(self.state, BEvent(turn=self.state.turn_number, actor=pet.persistent.name, action="status_tick",
                    detail={"status":"灼烧","damage":dmg,"stacks_before":s}))
            if pet.has_status(StatusFlag.POISON):
                s = pet.get_status_count(StatusType.POISON)
                dmg = calc_poison_damage(pet.max_hp, s)
                pet.current_hp = max(0, pet.current_hp - dmg)
                if enemy.has_ability_flag(AbilityFlag.EXTRA_POISON_TICK):
                    pet.current_hp = max(0, pet.current_hp - dmg)
                record_event(self.state, BEvent(turn=self.state.turn_number, actor=pet.persistent.name, action="status_tick",
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
                    pet.cooldowns = self._tick_cooldowns(pet.cooldowns)
                    if pet._cost_mod_turns > 0:
                        pet._cost_mod_turns -= 1
                        if pet._cost_mod_turns <= 0:
                            pet._cost_mod = 0

        a_pet, b_pet = s.team_a[s.active_a], s.team_b[s.active_b]
        a_first = self._acts_first(a_pet, b_pet, move_a, move_b)

        a_cat, b_cat = self._cat(a_pet, move_a), self._cat(b_pet, move_b)
        a_ctr, b_ctr = resolve_counter(a_cat, b_cat)
        if a_ctr: self.bus.emit(EventCtx(GameEvent.COUNTER_SUCCESS, s, actor=a_pet, target=b_pet, skill=self._skill(a_pet, move_a)))
        if b_ctr: self.bus.emit(EventCtx(GameEvent.COUNTER_SUCCESS, s, actor=b_pet, target=a_pet, skill=self._skill(b_pet, move_b)))

        f_pet = a_pet if a_first else b_pet; s_pet = b_pet if a_first else a_pet
        f_mv = move_a if a_first else move_b; s_mv = move_b if a_first else move_a
        f_team = "a" if a_first else "b"; s_team = "b" if a_first else "a"
        s.last_action_order = (f_team, s_team)
        c1 = (f_team=="a" and b_ctr) or (f_team=="b" and a_ctr)
        self._exec(f_pet, s_pet, f_mv, f_team, s, c1, first_strike=True)
        if not s_pet.is_fainted:
            c2 = (s_team=="a" and b_ctr) or (s_team=="b" and a_ctr)
            self._exec(s_pet, f_pet, s_mv, s_team, s, c2, first_strike=False)

        self.bus.emit(EventCtx(GameEvent.TURN_END, s))
        self._check_win(s)
        return s

    def is_finished(self): return self.state.winner is not None
    def get_winner(self): return self.state.winner

    def get_active(self, team: str) -> ActivePet:
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
                if can_use_skill(pet.current_energy, apply_marks_to_skill_cost(m.energy + pet._cost_mod, marks, is_attack=m.category.name in {"PHYSICAL", "MAGICAL"}))
                and _cooldown_at(pet.cooldowns, i) <= 0]

    # ── Internal ────────────────────────────────────────────────

    def _cat(self, pet: ActivePet, d: MoveDecision) -> SkillCategory:
        if d.action != "move" or d.skill_index is None: return SkillCategory.PHYSICAL
        idx = d.skill_index
        if idx < 0 or idx >= len(pet.persistent.moves): return SkillCategory.PHYSICAL
        return pet.persistent.moves[idx].category

    def _skill(self, pet: ActivePet, d: MoveDecision) -> SkillData | None:
        if d.action != "move" or d.skill_index is None:
            return None
        if 0 <= d.skill_index < len(pet.persistent.moves):
            return pet.persistent.moves[d.skill_index]
        return None

    def _priority(self, pet: ActivePet, d: MoveDecision) -> int:
        if d.action == "switch":
            return 6
        skill = self._skill(pet, d)
        return skill.priority_mod if skill else 0

    def _acts_first(self, a_pet: ActivePet, b_pet: ActivePet, move_a: MoveDecision, move_b: MoveDecision) -> bool:
        a_pri = self._priority(a_pet, move_a)
        b_pri = self._priority(b_pet, move_b)
        if a_pri != b_pri:
            return a_pri > b_pri
        a_spd = apply_marks_to_speed(a_pet.speed, self.state.marks_a)
        b_spd = apply_marks_to_speed(b_pet.speed, self.state.marks_b)
        if a_spd != b_spd:
            return a_spd > b_spd
        return bool(self.rng.getrandbits(1))

    @staticmethod
    def _tick_cooldowns(packed: int) -> int:
        return _tick_cooldowns(packed)

    def _exec(self, actor: ActivePet, target: ActivePet, d: MoveDecision, team: str,
              state: BattleState, countered: bool, *, first_strike: bool):
        if actor.is_fainted: return
        if d.action == "switch":
            self._do_switch(actor, d, team, state)
        elif d.action == "move" and d.skill_index is not None:
            from roco.engine.skill_exec import execute_move
            execute_move(actor, target, d.skill_index, state, countered, team=team, first_strike=first_strike)
            if target.current_hp <= 0:
                self._handle_faint(target)

    def _do_switch(self, switcher: ActivePet, d: MoveDecision, team: str, state: BattleState):
        pets = state.team_a if team == "a" else state.team_b
        if d.switch_slot is None: return
        new_idx = d.switch_slot
        if new_idx < 0 or new_idx >= len(pets): return
        new_pet = pets[new_idx]
        if new_pet.is_fainted: return

        self.bus.emit(EventCtx(GameEvent.SWITCH_OUT, state, actor=switcher, team=team))
        opp_team = "b" if team == "a" else "a"
        opp_active = state.team_b[state.active_b] if team == "a" else state.team_a[state.active_a]
        self.bus.emit(EventCtx(GameEvent.ENEMY_SWITCH, state, actor=opp_active, team=opp_team))

        switcher.reset_volatile()
        switcher.clear_switch_status()
        switcher.charging_skill = -1
        switcher._defense_reduction = 0

        record_event(state, BEvent(turn=state.turn_number, actor=switcher.persistent.name, action="switch",
            detail={"from":switcher.persistent.name, "to":new_pet.persistent.name}))

        if team == "a": state.active_a = new_idx
        else: state.active_b = new_idx

        new_pet.current_energy = max(0, new_pet.current_energy)
        self.bus.emit(EventCtx(GameEvent.SWITCH_IN, state, actor=new_pet, team=team))

    def _handle_faint(self, pet: ActivePet):
        if pet.is_fainted and pet.current_hp == 0:
            return
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
                record_event(self.state, BEvent(turn=self.state.turn_number, actor=p.persistent.name,
                    action="switch", detail={"auto":True,"reason":"faint_replace"}))
                self.bus.emit(EventCtx(GameEvent.SWITCH_IN, self.state, actor=p,
                    team="a" if is_a else "b"))
                return

    def _check_win(self, state: BattleState):
        if state.magic_a <= 0 or all(p.is_fainted for p in state.team_a):
            state.winner = "b"
        elif state.magic_b <= 0 or all(p.is_fainted for p in state.team_b):
            state.winner = "a"
        elif state.turn_number >= self.max_turns:
            state.winner = "draw"
