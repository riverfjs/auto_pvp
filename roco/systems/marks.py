"""Mark system — team-wide persistent buffs stored in packed ints."""

from __future__ import annotations
from roco.engine.state import MarkIdx, _unpack_mark, _set_mark

POISON_DMG_PCT = 0.03; THORN_HP_PCT = 0.06; SPIRIT_ENERGY_LOSS = 1
SOLAR_ENERGY = 1; SLOW_SPEED_REDUCE = 10; MOISTURE_COST_REDUCE = 1
METEOR_EXTRA_DMG = 30


def apply_marks_to_speed(speed: int, marks: int) -> int:
    stacks = _unpack_mark(marks, MarkIdx.SLOW)
    return max(1, speed - stacks * SLOW_SPEED_REDUCE)


def apply_marks_to_skill_cost(cost: int, marks: int, *, is_attack: bool = False) -> int:
    stacks = _unpack_mark(marks, MarkIdx.MOISTURE)
    momentum = _unpack_mark(marks, MarkIdx.MOMENTUM) if is_attack else 0
    return max(0, cost - stacks * MOISTURE_COST_REDUCE + momentum)


def apply_marks_to_attack_power(
    power: int,
    element: str,
    marks: int,
    atk_element: str,
    *,
    first_strike: bool = False,
    base_energy: int = 0,
) -> float:
    mult = 1.0
    a = _unpack_mark(marks, MarkIdx.ATTACK)
    if a > 0: mult += a * 0.10
    m = _unpack_mark(marks, MarkIdx.MOMENTUM)
    if m > 0: mult += m * 0.30
    w = _unpack_mark(marks, MarkIdx.WIND)
    if w > 0 and first_strike: mult += w * 0.20
    sg = _unpack_mark(marks, MarkIdx.SLUGGISH)
    if sg > 0 and not first_strike: mult += sg * 0.30
    d = _unpack_mark(marks, MarkIdx.DRAGON)
    if d > 0 and base_energy == 5: mult += d * 0.40
    return mult


def apply_marks_on_enter(pet, marks: int) -> tuple[int, int]:
    hp_loss = 0; energy_loss = 0
    thorn = _unpack_mark(marks, MarkIdx.THORN)
    if thorn > 0: hp_loss = int(pet.max_hp * thorn * THORN_HP_PCT)
    spirit = _unpack_mark(marks, MarkIdx.SPIRIT)
    if spirit > 0: energy_loss = spirit * SPIRIT_ENERGY_LOSS
    return hp_loss, energy_loss


def tick_marks_end_of_turn(pet, marks: int) -> tuple[int, int]:
    hp_loss = 0; energy_gain = 0
    poison = _unpack_mark(marks, MarkIdx.POISON)
    if poison > 0 and pet.current_hp > 0:
        hp_loss += int(pet.max_hp * poison * POISON_DMG_PCT)
    solar = _unpack_mark(marks, MarkIdx.SOLAR)
    if solar > 0: energy_gain += solar * SOLAR_ENERGY
    return hp_loss, energy_gain


def calc_meteor_extra_damage(marks: int) -> int:
    stacks = _unpack_mark(marks, MarkIdx.METEOR)
    return stacks * METEOR_EXTRA_DMG if stacks > 0 else 0


def register_mark_stage_hooks(bus):
    from roco.engine.events import GameEvent, EventCtx
    from roco.config.constants import MAX_ENERGY

    def on_switch_in(ctx):
        pet = ctx.actor
        if not pet: return
        marks = ctx.state.marks_a if (ctx.team or "a") == "a" else ctx.state.marks_b
        hp_loss, energy_loss = apply_marks_on_enter(pet, marks)
        if hp_loss > 0: pet.current_hp = max(0, pet.current_hp - hp_loss)
        if energy_loss > 0: pet.current_energy = max(0, pet.current_energy - energy_loss)

    def on_turn_end(ctx):
        s = ctx.state
        for tid, team, active in (("a", s.team_a, s.active_a), ("b", s.team_b, s.active_b)):
            marks = s.marks_a if tid == "a" else s.marks_b
            pet = team[active]
            if pet.is_fainted: continue
            hp_loss, energy_gain = tick_marks_end_of_turn(pet, marks)
            if hp_loss > 0: pet.current_hp = max(0, pet.current_hp - hp_loss)
            if energy_gain > 0: pet.current_energy = min(MAX_ENERGY, pet.current_energy + energy_gain)

    bus.on(GameEvent.SWITCH_IN, on_switch_in, priority=80, source="marks")
    bus.on(GameEvent.TURN_END, on_turn_end, priority=200, source="marks")
