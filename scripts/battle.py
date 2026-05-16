"""Turn-based battle engine for Roco Kingdom PVP simulation.

Deterministic: same inputs + same move choices = same outcome.
Randomness comes from the policy layer, NOT the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from scripts.damage import (
    compute_stats,
    calc_attack_damage,
    calc_burn_damage,
    calc_burn_decay,
    calc_poison_damage,
    get_type_multiplier,
    can_use_skill,
    calc_energy_after_gain,
    calc_energy_after_use,
    apply_buff_stages,
    clamp_stage,
)
from scripts.battle_config import (
    ENERGY_GAIN_PER_TURN,
    STARTING_ENERGY,
    MAX_ENERGY,
    DEFAULT_MAX_TURNS,
    STATUS_ELEMENT_IMMUNITY,
)
from scripts.type_chart import TYPES


# ── Data classes ───────────────────────────────────────────────

@dataclass
class SkillRef:
    name: str
    element: str
    category: str       # 物攻 / 魔攻 / 防御 / 状态
    energy: int
    power: int
    effect: str = ""


@dataclass
class PetState:
    """Runtime state of a single pet during battle."""
    name: str
    base_stats: dict[str, int]          # raw from DB
    effective_stats: dict[str, int]     # after nature + IV + buffs
    element_primary: str
    element_secondary: str = ""
    bloodline: str = ""
    nature: str = ""
    ivs: list[str] = field(default_factory=list)
    moves: list[SkillRef] = field(default_factory=list)
    current_hp: int = 0
    current_energy: int = STARTING_ENERGY
    buff_stages: dict[str, int] = field(default_factory=dict)
    status_stacks: dict[str, int] = field(default_factory=dict)
    is_fainted: bool = False
    slot: int = 0
    ability_name: str = ""
    ability_desc: str = ""

    @property
    def max_hp(self) -> int:
        return self.effective_stats.get("hp", 1)

    @property
    def speed(self) -> int:
        return self.effective_stats.get("speed", 0)

    @property
    def hp_pct(self) -> float:
        return self.current_hp / self.max_hp if self.max_hp > 0 else 0

    @property
    def defender_types(self) -> tuple[str, ...]:
        types = [self.element_primary]
        if self.element_secondary:
            types.append(self.element_secondary)
        return tuple(types)

    def is_immune_to_status(self, status: str) -> bool:
        for elem, sname in STATUS_ELEMENT_IMMUNITY.items():
            if sname == status and elem in self.defender_types:
                return True
        return False


@dataclass
class BattleEvent:
    turn: int
    actor: str           # pet name
    action: str           # "attack", "switch", "faint", "status_tick", "energy_gain", "buff"
    detail: dict = field(default_factory=dict)


@dataclass
class MoveDecision:
    """A player's decision for one turn."""
    action: str           # "move" or "switch"
    skill_index: int | None = None   # 0-3 for "move"
    switch_slot: int | None = None   # 0-5 for "switch"


@dataclass
class BattleState:
    team_a: list[PetState]
    team_b: list[PetState]
    active_a: int        # index into team_a
    active_b: int        # index into team_b
    turn_number: int = 0
    log: list[BattleEvent] = field(default_factory=list)
    winner: str | None = None   # "a", "b", "draw"


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
        # Set starting HP
        for pet in team_a + team_b:
            pet.current_hp = pet.max_hp
            pet.current_energy = STARTING_ENERGY
            pet.buff_stages = {}
            pet.status_stacks = {}
            pet.is_fainted = False

    # ── public API ──────────────────────────────────────────────

    def step(self, move_a: MoveDecision, move_b: MoveDecision) -> BattleState:
        """Execute one full turn. Returns updated state."""
        state = self.state
        state.turn_number += 1

        # 1. Start of turn: energy gain
        self._start_of_turn()

        # 2. Resolve turn order by speed
        a_pet = state.team_a[state.active_a]
        b_pet = state.team_b[state.active_b]
        a_first = a_pet.speed >= b_pet.speed

        first_pet, second_pet = (a_pet, b_pet) if a_first else (b_pet, a_pet)
        first_move, second_move = (move_a, move_b) if a_first else (move_b, move_a)
        first_team, second_team = ("a", "b") if a_first else ("b", "a")

        # 3. Execute faster pet
        self._execute_decision(first_pet, second_pet, first_move, first_team, state)

        if not second_pet.is_fainted:
            # 4. Execute slower pet
            self._execute_decision(second_pet, first_pet, second_move, second_team, state)

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
        """Indices of moves the active pet can afford."""
        pet = self.get_active(team)
        return [i for i, m in enumerate(pet.moves) if can_use_skill(pet.current_energy, m.energy)]

    # ── internal ────────────────────────────────────────────────

    def _start_of_turn(self) -> None:
        state = self.state
        for team in (state.team_a, state.team_b):
            for pet in team:
                if not pet.is_fainted:
                    pet.current_energy = calc_energy_after_gain(pet.current_energy)

    def _execute_decision(self, actor: PetState, target: PetState,
                          decision: MoveDecision, team: str,
                          state: BattleState) -> None:
        if actor.is_fainted:
            return

        if decision.action == "switch":
            self._do_switch(actor, decision, team, state)
        elif decision.action == "move" and decision.skill_index is not None:
            self._do_move(actor, target, decision.skill_index, state)

    def _do_move(self, attacker: PetState, defender: PetState,
                 skill_index: int, state: BattleState) -> None:
        if skill_index < 0 or skill_index >= len(attacker.moves):
            return

        skill = attacker.moves[skill_index]
        if not can_use_skill(attacker.current_energy, skill.energy):
            return  # struggle — skip for now

        attacker.current_energy = calc_energy_after_use(attacker.current_energy, skill.energy)

        if skill.category in ("物攻", "魔攻"):
            self._execute_damage_move(attacker, defender, skill, state)
        elif skill.category == "状态":
            self._execute_status_move(attacker, defender, skill, state)
        elif skill.category == "防御":
            self._execute_defense_move(attacker, skill, state)

    def _execute_damage_move(self, attacker: PetState, defender: PetState,
                             skill: SkillRef, state: BattleState) -> None:
        # Determine stat pair
        if skill.category == "物攻":
            atk = attacker.effective_stats["atk_phys"]
            dfn = defender.effective_stats["def_phys"]
        else:
            atk = attacker.effective_stats["atk_mag"]
            dfn = defender.effective_stats["def_mag"]

        # Apply attacker's buff stages
        if attacker.buff_stages:
            buffed = apply_buff_stages(attacker.effective_stats, attacker.buff_stages)
            if skill.category == "物攻":
                atk = buffed["atk_phys"]
            else:
                atk = buffed["atk_mag"]

        # Apply defender's buff stages
        if defender.buff_stages:
            buffed = apply_buff_stages(defender.effective_stats, defender.buff_stages)
            if skill.category == "物攻":
                dfn = buffed["def_phys"]
            else:
                dfn = buffed["def_mag"]

        type_mult = get_type_multiplier(skill.element, defender.defender_types)
        damage = calc_attack_damage(skill.power, atk, dfn, type_mult)
        defender.current_hp = max(0, defender.current_hp - damage)

        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=attacker.name,
            action="attack",
            detail={
                "move": skill.name, "damage": damage,
                "target": defender.name, "type_mult": type_mult,
                "target_hp_pct": round(defender.hp_pct * 100, 1),
            },
        ))

        # Apply on-hit status from skill effect text
        self._apply_status_from_effect(attacker, defender, skill.effect, state)

        if defender.current_hp <= 0:
            self._handle_faint(defender, state)

    def _execute_status_move(self, attacker: PetState, defender: PetState,
                             skill: SkillRef, state: BattleState) -> None:
        self._apply_status_from_effect(attacker, defender, skill.effect, state)
        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=attacker.name,
            action="attack",
            detail={"move": skill.name, "type": "status", "target": defender.name},
        ))

    def _execute_defense_move(self, attacker: PetState, skill: SkillRef,
                              state: BattleState) -> None:
        # Defense moves buff self
        if "减伤" in skill.effect:
            # Approximate: buff both defenses
            attacker.buff_stages["def_phys"] = clamp_stage(
                attacker.buff_stages.get("def_phys", 0) + 1)
            attacker.buff_stages["def_mag"] = clamp_stage(
                attacker.buff_stages.get("def_mag", 0) + 1)
        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=attacker.name,
            action="buff",
            detail={"move": skill.name, "type": "defense"},
        ))

    def _apply_status_from_effect(self, attacker: PetState, defender: PetState,
                                  effect: str, state: BattleState) -> None:
        """Naive keyword matching to apply status effects from move text."""
        if not effect:
            return

        if "灼烧" in effect and not defender.is_immune_to_status("灼烧"):
            stacks = defender.status_stacks.get("灼烧", 0) + 1
            defender.status_stacks["灼烧"] = stacks
            state.log.append(BattleEvent(
                turn=state.turn_number,
                actor=attacker.name,
                action="status_tick",
                detail={"status": "灼烧", "stacks": stacks, "target": defender.name},
            ))

        if "中毒" in effect and not defender.is_immune_to_status("中毒"):
            stacks = defender.status_stacks.get("中毒", 0) + 1
            defender.status_stacks["中毒"] = stacks

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

    def _handle_faint(self, pet: PetState, state: BattleState) -> None:
        pet.is_fainted = True
        pet.current_hp = 0
        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=pet.name,
            action="faint",
        ))

        # Auto-switch to first available bench pet
        team = state.team_a if pet in state.team_a else state.team_b
        is_a = team is state.team_a
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
        for team in (state.team_a, state.team_b):
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
                        turn=state.turn_number,
                        actor=pet.name,
                        action="status_tick",
                        detail={"status": "灼烧", "damage": dmg, "stacks_before": stacks},
                    ))
                    pet.status_stacks["灼烧"] = calc_burn_decay(stacks)

                # Poison tick
                if "中毒" in pet.status_stacks:
                    stacks = pet.status_stacks["中毒"]
                    dmg = calc_poison_damage(pet.max_hp, stacks)
                    pet.current_hp = max(0, pet.current_hp - dmg)
                    state.log.append(BattleEvent(
                        turn=state.turn_number,
                        actor=pet.name,
                        action="status_tick",
                        detail={"status": "中毒", "damage": dmg},
                    ))

                if pet.current_hp <= 0:
                    self._handle_faint(pet, state)

    def _check_win(self, state: BattleState) -> None:
        a_alive = any(not p.is_fainted for p in state.team_a)
        b_alive = any(not p.is_fainted for p in state.team_b)

        if not a_alive and not b_alive:
            state.winner = "draw"
        elif not a_alive:
            state.winner = "b"
        elif not b_alive:
            state.winner = "a"
        elif state.turn_number >= self.max_turns:
            state.winner = "draw"
