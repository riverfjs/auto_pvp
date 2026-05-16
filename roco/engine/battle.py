"""Turn-based battle engine — emits events, subsystems react via EventBus.

Deterministic: same inputs + same move choices = same outcome.
"""

from __future__ import annotations

from roco.engine.damage import (
    calc_energy_after_gain, can_use_skill,
)
from roco.engine.state import (
    PetState, BattleEvent as BEvent, MoveDecision, BattleState,
)
from roco.engine.skill_exec import execute_move, get_skill_category
from roco.engine.skill_exec import execute_move, get_skill_category
from roco.engine.events import EventBus, EventCtx, GameEvent
from roco.config.constants import (
    ENERGY_GAIN_PER_TURN, STARTING_ENERGY, MAX_ENERGY, DEFAULT_MAX_TURNS,
)
from roco.systems.marks import apply_marks_to_speed, apply_marks_to_skill_cost
from roco.systems.counter import resolve_counter
from roco.engine.ability import register_ability_handlers


class BattleEngine:
    """Deterministic battle simulator. Events-based architecture."""

    def __init__(self, team_a: list[PetState], team_b: list[PetState],
                 max_turns: int = DEFAULT_MAX_TURNS):
        self.max_turns = max_turns
        if not team_a or not team_b:
            raise ValueError("Both teams must have at least 1 pet")

        self.state = BattleState(team_a=team_a, team_b=team_b,
                                 active_a=0, active_b=0)

        # ── Event bus + subsystem registration ──
        self.bus = EventBus()
        self._init_systems()
        self._register_engine_handlers()

        # Init pets + register their abilities
        for pet in team_a + team_b:
            pet.current_hp = pet.max_hp
            pet.current_energy = STARTING_ENERGY
            pet.buff_stages = {}
            pet.status_stacks = {}
            pet.is_fainted = False
            register_ability_handlers(self.bus, pet)

        # Emit BATTLE_START then SWITCH_IN for starting pets
        self.bus.emit(EventCtx(GameEvent.BATTLE_START, self.state))
        for team, pet in (("a", team_a[0]), ("b", team_b[0])):
            self.bus.emit(EventCtx(GameEvent.SWITCH_IN, self.state, actor=pet,
                                   data={"team": team}))

    def _init_systems(self) -> None:
        """Explicitly construct all game subsystems — no import-time side effects."""
        from roco.systems.weather import register_weather_handlers
        from roco.systems.marks import register_mark_handlers
        from roco.engine.skill_exec import register_skill_handlers
        register_weather_handlers(self.bus)
        register_mark_handlers(self.bus)
        register_skill_handlers(self.bus)

    # ── Event handlers registered by engine itself ──────────────

    def _register_engine_handlers(self) -> None:
        bus = self.bus
        bus.on(GameEvent.FAINT, self._on_faint_magic, priority=999, source="engine")
        bus.on(GameEvent.TURN_END, self._on_turn_end_status, priority=300, source="engine")

    def _on_faint_magic(self, ctx: EventCtx) -> None:
        """Engine-level: deduct magic_power on faint (except 诈死)."""
        pet = ctx.actor
        if not pet:
            return
        state = ctx.state
        is_a = pet in state.team_a
        magic_cost = 0 if "诈死" in pet.ability_name else 1
        if is_a:
            state.magic_a = max(0, state.magic_a - magic_cost)
        else:
            state.magic_b = max(0, state.magic_b - magic_cost)
        state.log.append(BEvent(
            turn=state.turn_number, actor=pet.name, action="faint",
            detail={"magic_cost": magic_cost,
                    "magic_remaining": state.magic_a if is_a else state.magic_b},
        ))

    def _on_turn_end_status(self, ctx: EventCtx) -> None:
        """Engine-level: per-pet burn/poison status ticks."""
        from roco.engine.damage import (
            calc_burn_damage, calc_burn_decay, calc_poison_damage,
            get_type_multiplier,
        )
        state = ctx.state
        for pet in state.team_a + state.team_b:
            if pet.is_fainted:
                continue
            if "灼烧" in pet.status_stacks:
                stacks = pet.status_stacks["灼烧"]
                tm = get_type_multiplier("火", pet.defender_types)
                dmg = calc_burn_damage(pet.max_hp, stacks, tm, mid_turn=False)
                pet.current_hp = max(0, pet.current_hp - dmg)
                pet.status_stacks["灼烧"] = calc_burn_decay(stacks)
                state.log.append(BEvent(
                    turn=state.turn_number, actor=pet.name, action="status_tick",
                    detail={"status": "灼烧", "damage": dmg, "stacks_before": stacks},
                ))
            if "中毒" in pet.status_stacks:
                stacks = pet.status_stacks["中毒"]
                dmg = calc_poison_damage(pet.max_hp, stacks)
                pet.current_hp = max(0, pet.current_hp - dmg)
                state.log.append(BEvent(
                    turn=state.turn_number, actor=pet.name, action="status_tick",
                    detail={"status": "中毒", "damage": dmg},
                ))
            if pet.current_hp <= 0:
                self._handle_faint(pet, state)

    # ── public API ──────────────────────────────────────────────

    def step(self, move_a: MoveDecision, move_b: MoveDecision) -> BattleState:
        state = self.state
        state.turn_number += 1

        # TURN_START event (before energy gain)
        self.bus.emit(EventCtx(GameEvent.TURN_START, state))

        # Energy gain
        for team in (state.team_a, state.team_b):
            for pet in team:
                if not pet.is_fainted:
                    pet.current_energy = calc_energy_after_gain(pet.current_energy)

        # Speed order (with priority_mod from selected skills)
        a_pet = state.team_a[state.active_a]
        b_pet = state.team_b[state.active_b]
        a_prio = self._priority(a_pet, move_a)
        b_prio = self._priority(b_pet, move_b)
        a_speed = apply_marks_to_speed(a_pet.speed, state.marks_a) + a_prio
        b_speed = apply_marks_to_speed(b_pet.speed, state.marks_b) + b_prio
        a_first = a_speed >= b_speed

        first_pet = a_pet if a_first else b_pet
        second_pet = b_pet if a_first else a_pet
        first_move = move_a if a_first else move_b
        second_move = move_b if a_first else move_a
        first_team = "a" if a_first else "b"
        second_team = "b" if a_first else "a"

        # Counter resolution
        a_cat = self._cat(a_pet, move_a)
        b_cat = self._cat(b_pet, move_b)
        a_ctr, b_ctr = resolve_counter(a_cat, b_cat)
        if a_ctr:
            self.bus.emit(EventCtx(GameEvent.COUNTER_SUCCESS, state, actor=a_pet, target=b_pet))
            self.bus.emit(EventCtx(GameEvent.ALLY_COUNTER, state, actor=a_pet, data={"team": "a"}))
        if b_ctr:
            self.bus.emit(EventCtx(GameEvent.COUNTER_SUCCESS, state, actor=b_pet, target=a_pet))
            self.bus.emit(EventCtx(GameEvent.ALLY_COUNTER, state, actor=b_pet, data={"team": "b"}))

        # Execute faster
        countered_1 = (first_team == "a" and b_ctr) or (first_team == "b" and a_ctr)
        self._exec(first_pet, second_pet, first_move, first_team, state, countered_1)

        if not second_pet.is_fainted:
            countered_2 = (second_team == "a" and b_ctr) or (second_team == "b" and a_ctr)
            self._exec(second_pet, first_pet, second_move, second_team, state, countered_2)

        # TURN_END event (weather, marks, status ticks)
        self.bus.emit(EventCtx(GameEvent.TURN_END, state))

        self._check_win(state)
        return state

    def is_finished(self) -> bool:
        return self.state.winner is not None

    def get_winner(self) -> str | None:
        return self.state.winner

    def get_active(self, team: str) -> PetState:
        idx = self.state.active_a if team == "a" else self.state.active_b
        return (self.state.team_a if team == "a" else self.state.team_b)[idx]

    def get_available_switches(self, team: str) -> list[int]:
        pets = self.state.team_a if team == "a" else self.state.team_b
        active = self.state.active_a if team == "a" else self.state.active_b
        return [i for i, p in enumerate(pets) if i != active and not p.is_fainted]

    def get_valid_moves(self, team: str) -> list[int]:
        pet = self.get_active(team)
        if pet.charging_skill_idx >= 0:
            return [pet.charging_skill_idx]
        marks = self.state.marks_a if team == "a" else self.state.marks_b
        return [i for i, m in enumerate(pet.moves)
                if can_use_skill(pet.current_energy,
                               apply_marks_to_skill_cost(m.energy, marks))
                and pet.cooldowns.get(i, 0) <= 0]

    # ── internal ────────────────────────────────────────────────

    def _cat(self, pet: PetState, decision: MoveDecision) -> str:
        return get_skill_category(pet, decision.skill_index or 0)

    def _priority(self, pet: PetState, decision: MoveDecision) -> int:
        """Get priority modifier from the selected move (or 0 if switching)."""
        if decision.action != "move" or decision.skill_index is None:
            return 0
        idx = decision.skill_index
        if idx < 0 or idx >= len(pet.moves):
            return 0
        return pet.moves[idx].priority_mod

    def _exec(self, actor: PetState, target: PetState,
              decision: MoveDecision, team: str,
              state: BattleState, countered: bool = False) -> None:
        if actor.is_fainted:
            return
        if decision.action == "switch":
            self._do_switch(actor, decision, team, state)
        elif decision.action == "move" and decision.skill_index is not None:
            # BEFORE_MOVE event (can cancel via ctx.cancelled)
            ctx = EventCtx(GameEvent.BEFORE_MOVE, state, actor=actor, target=target,
                           data={"team": team, "countered": countered,
                                 "skill_index": decision.skill_index})
            self.bus.emit(ctx)
            if ctx.cancelled:
                return
            actor._turn_power_mod = ctx.power_mod
            hp_before = target.current_hp
            execute_move(actor, target, decision.skill_index, state, countered)
            actor._turn_power_mod = 1.0
            dmg_taken = hp_before - target.current_hp
            skill = actor.moves[decision.skill_index] if decision.skill_index < len(actor.moves) else None
            if dmg_taken > 0:
                self.bus.emit(EventCtx(GameEvent.AFTER_DAMAGE, state,
                    actor=actor, target=target,
                    data={"damage": dmg_taken, "skill": skill}))
                self.bus.emit(EventCtx(GameEvent.TAKE_DAMAGE, state,
                    actor=target, target=actor,
                    data={"damage": dmg_taken}))
            # AFTER_MOVE (for force switch etc.)
            self.bus.emit(EventCtx(GameEvent.AFTER_MOVE, state,
                actor=actor, target=target,
                data={"skill": skill, "damage": dmg_taken}))
            if target.current_hp <= 0:
                self._handle_faint(target, state)

    def _do_switch(self, switcher: PetState, decision: MoveDecision,
                   team: str, state: BattleState) -> None:
        pets = state.team_a if team == "a" else state.team_b
        if decision.switch_slot is None:
            return
        new_idx = decision.switch_slot
        if new_idx < 0 or new_idx >= len(pets):
            return
        new_pet = pets[new_idx]
        if new_pet.is_fainted:
            return

        # SWITCH_OUT + ENEMY_SWITCH events
        self.bus.emit(EventCtx(GameEvent.SWITCH_OUT, state, actor=switcher,
                               data={"team": team}))
        opp_team_id = "b" if team == "a" else "a"
        opp_pet = state.team_b[state.active_b] if team == "a" else state.team_a[state.active_a]
        self.bus.emit(EventCtx(GameEvent.ENEMY_SWITCH, state, actor=opp_pet,
                               data={"team": opp_team_id}))
        switcher.charging_skill_idx = -1

        state.log.append(BEvent(
            turn=state.turn_number, actor=switcher.name, action="switch",
            detail={"from": switcher.name, "to": new_pet.name},
        ))

        if team == "a":
            state.active_a = new_idx
        else:
            state.active_b = new_idx

        new_pet.current_energy = max(new_pet.current_energy, 0)

        # SWITCH_IN event (marks + abilities trigger through this)
        self.bus.emit(EventCtx(GameEvent.SWITCH_IN, state, actor=new_pet,
                               data={"team": team}))

    def _handle_faint(self, pet: PetState, state: BattleState) -> None:
        pet.is_fainted = True
        pet.current_hp = 0

        # Find killer
        killer: PetState | None = None
        for ev in reversed(state.log):
            if ev.action == "attack" and ev.detail.get("target") == pet.name:
                opp_team = state.team_b if pet in state.team_a else state.team_a
                for opp in opp_team:
                    if opp.name == ev.actor:
                        killer = opp
                        break
                break

        # FAINT event (magic cost handled by engine handler)
        self.bus.emit(EventCtx(GameEvent.FAINT, state, actor=pet,
                               target=killer))

        # KILL event (ability triggers for killer)
        if killer:
            self.bus.emit(EventCtx(GameEvent.KILL, state, actor=killer,
                                   target=pet))

        # Auto-switch
        team = state.team_a if pet in state.team_a else state.team_b
        is_a = team is state.team_a
        active_idx = state.active_a if is_a else state.active_b
        idx_in_team = team.index(pet) if pet in team else -1
        if idx_in_team != active_idx:
            return

        for i, p in enumerate(team):
            if i != active_idx and not p.is_fainted:
                if is_a:
                    state.active_a = i
                else:
                    state.active_b = i
                state.log.append(BEvent(
                    turn=state.turn_number, actor=p.name, action="switch",
                    detail={"auto": True, "reason": "faint_replace"},
                ))
                # SWITCH_IN for new active
                self.bus.emit(EventCtx(GameEvent.SWITCH_IN, state, actor=p,
                                       data={"team": "a" if is_a else "b",
                                             "auto": True}))
                return

    def _check_win(self, state: BattleState) -> None:
        a_magic = state.magic_a <= 0
        b_magic = state.magic_b <= 0
        a_wipe = all(p.is_fainted for p in state.team_a)
        b_wipe = all(p.is_fainted for p in state.team_b)
        a_active = state.team_a[state.active_a]
        b_active = state.team_b[state.active_b]

        a_lost = a_magic or a_wipe or (
            a_active.is_fainted and not self.get_available_switches("a"))
        b_lost = b_magic or b_wipe or (
            b_active.is_fainted and not self.get_available_switches("b"))

        if a_lost and b_lost:
            state.winner = "draw"
        elif a_lost:
            state.winner = "b"
        elif b_lost:
            state.winner = "a"
        elif state.turn_number >= self.max_turns:
            state.winner = "draw"
