"""Turn-based battle engine for Roco Kingdom PVP simulation.

Deterministic: same inputs + same move choices = same outcome.
Randomness comes from the policy layer, NOT the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from roco.engine.damage import (
    calc_burn_damage, calc_burn_decay, calc_poison_damage,
    get_type_multiplier, calc_energy_after_gain, can_use_skill,
    apply_buff_stages,
)
from roco.engine.state import (
    PetState, BattleEvent, MoveDecision, BattleState, DEFAULT_MAGIC_POWER,
)
from roco.engine.skill import execute_move, get_skill_category
from roco.engine.ability import trigger, AbilityTiming
from roco.config.constants import (
    ENERGY_GAIN_PER_TURN, STARTING_ENERGY, MAX_ENERGY,
    DEFAULT_MAX_TURNS,
)
from roco.systems.weather import sandstorm_chip_damage, snow_frostbite_damage, is_sandstorm_immune
from roco.systems.marks import apply_marks_to_speed, apply_marks_to_skill_cost, apply_marks_on_enter, tick_marks_end_of_turn
from roco.systems.counter import resolve_counter


# ── Battle engine ──────────────────────────────────────────────

class BattleEngine:
    """Deterministic battle simulator. Call step() per turn."""

    def __init__(self, team_a: list[PetState], team_b: list[PetState],
                 max_turns: int = DEFAULT_MAX_TURNS):
        self.max_turns = max_turns
        # Validate teams
        if not team_a or not team_b:
            raise ValueError("Both teams must have at least 1 pet")
        self.state = BattleState(
            team_a=team_a,
            team_b=team_b,
            active_a=0,
            active_b=0,
        )
        # Set starting HP + trigger passive abilities
        for pet in team_a + team_b:
            pet.current_hp = pet.max_hp
            pet.current_energy = STARTING_ENERGY
            pet.buff_stages = {}
            pet.status_stacks = {}
            pet.is_fainted = False
            trigger(pet, AbilityTiming.PASSIVE, self.state)

    # ── public API ──────────────────────────────────────────────

    def step(self, move_a: MoveDecision, move_b: MoveDecision) -> BattleState:
        """Execute one full turn. Returns updated state."""
        state = self.state
        state.turn_number += 1

        # 1. Start of turn: energy gain
        self._start_of_turn()

        # 2. Resolve turn order by speed (with mark-modified speed)
        a_pet = state.team_a[state.active_a]
        b_pet = state.team_b[state.active_b]
        a_speed = apply_marks_to_speed(a_pet.speed, state.marks_a)
        b_speed = apply_marks_to_speed(b_pet.speed, state.marks_b)
        a_first = a_speed >= b_speed

        first_pet, second_pet = (a_pet, b_pet) if a_first else (b_pet, a_pet)
        first_move, second_move = (move_a, move_b) if a_first else (move_b, move_a)
        first_team, second_team = ("a", "b") if a_first else ("b", "a")

        # 2.5 Resolve counter
        a_skill_cat = self._get_skill_cat(a_pet, move_a)
        b_skill_cat = self._get_skill_cat(b_pet, move_b)
        a_counters_b, b_counters_a = resolve_counter(a_skill_cat, b_skill_cat)

        # 3. Execute faster pet
        self._execute_decision(first_pet, second_pet, first_move, first_team, state,
                               countered=(first_team == "a" and b_counters_a) or
                                         (first_team == "b" and a_counters_b))

        if not second_pet.is_fainted:
            # 4. Execute slower pet
            self._execute_decision(second_pet, first_pet, second_move, second_team, state,
                                   countered=(second_team == "a" and b_counters_a) or
                                             (second_team == "b" and a_counters_b))

        # 5. End of turn: status ticks, burn decay, buff decay
        self._end_of_turn()

        # 6. Check win condition
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
        """Indices of non-fainted bench pets."""
        pets = self.state.team_a if team == "a" else self.state.team_b
        active_idx = self.state.active_a if team == "a" else self.state.active_b
        return [i for i, p in enumerate(pets) if i != active_idx and not p.is_fainted]

    def get_valid_moves(self, team: str) -> list[int]:
        """Indices of moves the active pet can use (energy + cooldown + charge)."""
        pet = self.get_active(team)
        # If charging, only the charged skill is valid
        if pet.charging_skill_idx >= 0:
            return [pet.charging_skill_idx]
        team_marks = self.state.marks_a if team == "a" else self.state.marks_b
        return [
            i for i, m in enumerate(pet.moves)
            if can_use_skill(pet.current_energy,
                           apply_marks_to_skill_cost(m.energy, team_marks))
            and pet.cooldowns.get(i, 0) <= 0
        ]

    # ── internal ────────────────────────────────────────────────

    def _start_of_turn(self) -> None:
        state = self.state
        for team in (state.team_a, state.team_b):
            for pet in team:
                if not pet.is_fainted:
                    pet.current_energy = calc_energy_after_gain(pet.current_energy)

    def _get_skill_cat(self, pet: PetState, decision: MoveDecision) -> str:
        return get_skill_category(pet, decision.skill_index or 0)


    def _execute_decision(self, actor: PetState, target: PetState,
                          decision: MoveDecision, team: str,
                          state: BattleState, countered: bool = False) -> None:
        if actor.is_fainted:
            return

        if decision.action == "switch":
            self._do_switch(actor, decision, team, state)
        elif decision.action == "move" and decision.skill_index is not None:
            execute_move(actor, target, decision.skill_index, state, countered)
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

        # Clear charge on switch-out
        switcher.charging_skill_idx = -1

        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=switcher.name,
            action="switch",
            detail={"from": switcher.name, "to": new_pet.name},
        ))

        if team == "a":
            state.active_a = new_idx
        else:
            state.active_b = new_idx

        new_pet.current_energy = max(new_pet.current_energy, 0)

        # Trigger ON_ENTER ability
        trigger(new_pet, AbilityTiming.ON_ENTER, state)

        # Apply mark on-enter effects
        marks = state.marks_a if team == "a" else state.marks_b
        mark_hp, mark_nrg = apply_marks_on_enter(new_pet, marks)
        if mark_hp > 0:
            new_pet.current_hp = max(0, new_pet.current_hp - mark_hp)
        if mark_nrg > 0:
            new_pet.current_energy = max(0, new_pet.current_energy - mark_nrg)

    def _handle_faint(self, pet: PetState, state: BattleState) -> None:
        pet.is_fainted = True
        pet.current_hp = 0

        # ── Ability triggers ──
        trigger(pet, AbilityTiming.ON_FAINT, state)
        # Find killer (last attacker) and trigger ON_KILL
        for ev in reversed(state.log):
            if ev.action == "attack" and ev.detail.get("target") == pet.name:
                killer_name = ev.actor
                opp_team = state.team_b if pet in state.team_a else state.team_a
                for opp in opp_team:
                    if opp.name == killer_name:
                        trigger(opp, AbilityTiming.ON_KILL, state, target=pet)
                        break
                break

        # Determine which team and apply magic_power cost
        team = state.team_a if pet in state.team_a else state.team_b
        is_a = team is state.team_a

        # "诈死" ability: fainting doesn't cost magic power
        magic_cost = 1
        if "诈死" in pet.ability_name:
            magic_cost = 0

        if is_a:
            state.magic_a = max(0, state.magic_a - magic_cost)
        else:
            state.magic_b = max(0, state.magic_b - magic_cost)

        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=pet.name,
            action="faint",
            detail={"magic_cost": magic_cost,
                    "magic_remaining": state.magic_a if is_a else state.magic_b},
        ))

        # Auto-switch to first available bench pet
        active_idx = state.active_a if is_a else state.active_b

        # Only auto-switch if this was the active pet
        idx_in_team = team.index(pet) if pet in team else -1
        if idx_in_team != active_idx:
            return

        for i, p in enumerate(team):
            if i != active_idx and not p.is_fainted:
                if is_a:
                    state.active_a = i
                else:
                    state.active_b = i
                state.log.append(BattleEvent(
                    turn=state.turn_number,
                    actor=p.name,
                    action="switch",
                    detail={"auto": True, "reason": "faint_replace"},
                ))
                return

    def _end_of_turn(self) -> None:
        state = self.state

        # ── Weather effects ──
        if state.weather == "sandstorm":
            for pet in state.team_a + state.team_b:
                if pet.is_fainted:
                    continue
                if is_sandstorm_immune(pet.element_primary):
                    continue
                dmg = sandstorm_chip_damage(pet.max_hp)
                pet.current_hp = max(0, pet.current_hp - dmg)
                state.log.append(BattleEvent(
                    turn=state.turn_number, actor=pet.name,
                    action="status_tick",
                    detail={"weather": "sandstorm", "damage": dmg},
                ))
                if pet.current_hp <= 0:
                    self._handle_faint(pet, state)

        elif state.weather == "snow":
            for pet in state.team_a + state.team_b:
                if pet.is_fainted:
                    continue
                frost = snow_frostbite_damage(pet.max_hp)
                pet.frostbite_damage += frost
                # Snow also applies 2 freeze stacks
                pet.status_stacks["冻结"] = pet.status_stacks.get("冻结", 0) + 2
                state.log.append(BattleEvent(
                    turn=state.turn_number, actor=pet.name,
                    action="status_tick",
                    detail={"weather": "snow", "frostbite": frost},
                ))

        # ── Weather duration ──
        if state.weather and state.weather_turns > 0:
            state.weather_turns -= 1
            if state.weather_turns <= 0:
                state.weather = None

        # ── Per-pet status & mark ticks ──
        for team_id, team in (("a", state.team_a), ("b", state.team_b)):
            marks = state.marks_a if team_id == "a" else state.marks_b
            for pet in team:
                if pet.is_fainted:
                    continue

                # Burn tick
                if "灼烧" in pet.status_stacks:
                    stacks = pet.status_stacks["灼烧"]
                    type_mult = get_type_multiplier("火", pet.defender_types)
                    dmg = calc_burn_damage(pet.max_hp, stacks, type_mult, mid_turn=False)
                    pet.current_hp = max(0, pet.current_hp - dmg)
                    state.log.append(BattleEvent(
                        turn=state.turn_number, actor=pet.name,
                        action="status_tick",
                        detail={"status": "灼烧", "damage": dmg, "stacks_before": stacks},
                    ))
                    pet.status_stacks["灼烧"] = calc_burn_decay(stacks)

                # Poison (individual status)
                if "中毒" in pet.status_stacks:
                    stacks = pet.status_stacks["中毒"]
                    dmg = calc_poison_damage(pet.max_hp, stacks)
                    pet.current_hp = max(0, pet.current_hp - dmg)
                    state.log.append(BattleEvent(
                        turn=state.turn_number, actor=pet.name,
                        action="status_tick",
                        detail={"status": "中毒", "damage": dmg},
                    ))

                # Mark end-of-turn effects (poison mark, solar mark)
                mark_hp_loss, mark_energy = tick_marks_end_of_turn(pet, marks)
                if mark_hp_loss > 0:
                    pet.current_hp = max(0, pet.current_hp - mark_hp_loss)
                if mark_energy > 0:
                    pet.current_energy = min(ENERGY_CAP, pet.current_energy + mark_energy)

                if pet.current_hp <= 0:
                    self._handle_faint(pet, state)

    def _check_win(self, state: BattleState) -> None:
        a_magic = state.magic_a <= 0
        b_magic = state.magic_b <= 0
        a_wipe = all(p.is_fainted for p in state.team_a)
        b_wipe = all(p.is_fainted for p in state.team_b)

        # Loss conditions: magic depleted OR all 6 fainted with no bench
        a_lost = a_magic or a_wipe
        b_lost = b_magic or b_wipe

        # Also check if active fainted but no switch available
        a_active = state.team_a[state.active_a]
        b_active = state.team_b[state.active_b]
        if a_active.is_fainted and not self.get_available_switches("a"):
            a_lost = True
        if b_active.is_fainted and not self.get_available_switches("b"):
            b_lost = True

        if a_lost and b_lost:
            state.winner = "draw"
        elif a_lost:
            state.winner = "b"
        elif b_lost:
            state.winner = "a"
        elif state.turn_number >= self.max_turns:
            state.winner = "draw"
