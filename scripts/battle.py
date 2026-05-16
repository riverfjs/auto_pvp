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
    get_stab,
    can_use_skill,
    calc_energy_after_gain,
    calc_energy_after_use,
    apply_buff_stages,
    clamp_stage,
)
from scripts.battle_config import (
    ENERGY_GAIN_PER_TURN,
    STARTING_ENERGY,
    ENERGY_CAP,
    MAX_ENERGY,
    DEFAULT_MAX_TURNS,
    STATUS_ELEMENT_IMMUNITY,
    COUNTER_DAMAGE_BONUS,
)
from scripts.systems.weather import (
    weather_damage_mult,
    sandstorm_chip_damage,
    snow_frostbite_damage,
    is_sandstorm_immune,
)
from scripts.systems.marks import (
    apply_marks_to_speed,
    apply_marks_to_skill_cost,
    apply_marks_to_attack_power,
    apply_marks_on_enter,
    tick_marks_end_of_turn,
    calc_meteor_extra_damage,
)
from scripts.systems.counter import resolve_counter
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
    frostbite_damage: int = 0          # 冻伤不可恢复伤害 (snow weather)
    power_multiplier: float = 1.0      # 独立威力乘层
    charging_skill_idx: int = -1        # -1=无蓄力, >=0=正在蓄力的招式index
    cooldowns: dict[int, int] = field(default_factory=dict)  # {skill_idx: remaining_cooldown}
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


DEFAULT_MAGIC_POWER: int = 4    # first to lose 4 KOs loses

@dataclass
class BattleState:
    team_a: list[PetState]
    team_b: list[PetState]
    active_a: int        # index into team_a
    active_b: int        # index into team_b
    magic_a: int = DEFAULT_MAGIC_POWER
    magic_b: int = DEFAULT_MAGIC_POWER
    weather: str | None = None
    weather_turns: int = 0
    marks_a: dict[str, float] = field(default_factory=dict)
    marks_b: dict[str, float] = field(default_factory=dict)
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
        if decision.action == "switch" or decision.skill_index is None:
            return ""
        idx = decision.skill_index
        if idx < 0 or idx >= len(pet.moves):
            return ""
        return pet.moves[idx].category


    def _execute_decision(self, actor: PetState, target: PetState,
                          decision: MoveDecision, team: str,
                          state: BattleState, countered: bool = False) -> None:
        if actor.is_fainted:
            return

        if decision.action == "switch":
            self._do_switch(actor, decision, team, state)
        elif decision.action == "move" and decision.skill_index is not None:
            self._do_move(actor, target, decision.skill_index, state, countered)

    def _do_move(self, attacker: PetState, defender: PetState,
                 skill_index: int, state: BattleState,
                 countered: bool = False) -> None:
        if skill_index < 0 or skill_index >= len(attacker.moves):
            return

        skill = attacker.moves[skill_index]

        # ── Charge resolution ──
        # If charging from previous turn, use the stored skill (regardless of decision)
        if attacker.charging_skill_idx >= 0:
            charge_idx = attacker.charging_skill_idx
            attacker.charging_skill_idx = -1
            if charge_idx < len(attacker.moves):
                skill = attacker.moves[charge_idx]
                skill_index = charge_idx

        # Check cooldown
        if attacker.cooldowns.get(skill_index, 0) > 0:
            return

        # Apply moisture mark cost reduction
        team_marks = state.marks_a if attacker in state.team_a else state.marks_b
        effective_cost = apply_marks_to_skill_cost(skill.energy, team_marks)

        if not can_use_skill(attacker.current_energy, effective_cost):
            return

        # ── Charge start: skip execution, set charge for next turn ──
        if "蓄力" in skill.effect:
            attacker.current_energy = calc_energy_after_use(
                attacker.current_energy, effective_cost)
            attacker.charging_skill_idx = skill_index
            state.log.append(BattleEvent(
                turn=state.turn_number, actor=attacker.name,
                action="buff",
                detail={"move": skill.name, "charge": True},
            ))
            return

        attacker.current_energy = calc_energy_after_use(
            attacker.current_energy, effective_cost)

        if skill.category in ("物攻", "魔攻"):
            self._execute_damage_move(attacker, defender, skill, state, countered)
        elif skill.category == "状态":
            self._execute_status_move(attacker, defender, skill, state)
        elif skill.category == "防御":
            self._execute_defense_move(attacker, skill, state)

        # ── Cooldown: reduce all existing cooldowns, set new one if applicable ──
        new_cd: dict[int, int] = {}
        for idx, cd in attacker.cooldowns.items():
            if cd > 1:
                new_cd[idx] = cd - 1
        if "应对" in skill.effect and "冷却" in skill.effect:
            # Skills with counter mechanics often have cooldowns
            new_cd[skill_index] = 2  # 2 turn cooldown
        attacker.cooldowns = new_cd

    def _execute_damage_move(self, attacker: PetState, defender: PetState,
                             skill: SkillRef, state: BattleState,
                             countered: bool = False) -> None:
        # Determine stat pair
        if skill.category == "物攻":
            atk = float(attacker.effective_stats["atk_phys"])
            dfn = float(defender.effective_stats["def_phys"])
        else:
            atk = float(attacker.effective_stats["atk_mag"])
            dfn = float(defender.effective_stats["def_mag"])

        # Apply buff stages
        if attacker.buff_stages:
            buffed = apply_buff_stages(attacker.effective_stats, attacker.buff_stages)
            if skill.category == "物攻":
                atk = float(buffed["atk_phys"])
            else:
                atk = float(buffed["atk_mag"])
        if defender.buff_stages:
            buffed = apply_buff_stages(defender.effective_stats, defender.buff_stages)
            if skill.category == "物攻":
                dfn = float(buffed["def_phys"])
            else:
                dfn = float(buffed["def_mag"])

        # Core multipliers
        type_mult = get_type_multiplier(skill.element, defender.defender_types)
        stab = get_stab(skill.element, attacker.element_primary)

        # Weather modifier (from attacker's marks/weather)
        weather_mult = weather_damage_mult(skill.element, state.weather)

        # Mark-based power buffs
        attacker_marks = state.marks_a if attacker in state.team_a else state.marks_b
        mark_power_buff = apply_marks_to_attack_power(
            skill.power, skill.element, attacker_marks, attacker.element_primary)

        # Counter bonus
        counter_buff = COUNTER_DAMAGE_BONUS if countered else 1.0

        # Combined power buff
        power_buff = (mark_power_buff * counter_buff *
                      attacker.power_multiplier)

        damage = calc_attack_damage(
            skill.power, atk, dfn, type_mult,
            stab=stab, weather_mult=weather_mult, power_buff=power_buff,
        )

        # Meteor mark extra damage (星陨 — 非幻系攻击触发幻系额外魔伤)
        defender_marks = state.marks_b if defender in state.team_b else state.marks_a
        if skill.element != "幻":
            meteor_dmg = calc_meteor_extra_damage(defender_marks)
            if meteor_dmg > 0:
                damage += meteor_dmg
                # Meteor stacks are consumed after triggering
                state.log.append(BattleEvent(
                    turn=state.turn_number,
                    actor=attacker.name,
                    action="status_tick",
                    detail={"status": "meteor", "extra_damage": meteor_dmg},
                ))

        # Apply frostbite HP reduction (effective max HP)
        effective_hp = defender.current_hp - defender.frostbite_damage
        defender.current_hp = max(0, min(effective_hp, defender.current_hp) - damage)
        if defender.frostbite_damage > 0:
            defender.current_hp = max(0, defender.current_hp)

        state.log.append(BattleEvent(
            turn=state.turn_number,
            actor=attacker.name,
            action="attack",
            detail={
                "move": skill.name, "damage": damage,
                "target": defender.name, "type_mult": type_mult,
                "stab": stab, "weather_mult": weather_mult,
                "countered": countered,
                "target_hp_pct": round(defender.hp_pct * 100, 1),
            },
        ))

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
