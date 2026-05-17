"""Shared helpers for compiled effect handlers."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from roco.engine.damage import clamp_stage
from roco.engine.enums import StatusFlag, StatusType, WeatherType
from roco.engine.events import EventCtx
from roco.engine.packing import MarkIdx, _set_mark, _unpack_mark
from roco.engine.state import ActivePet, BattleEvent, record_event


EffectParams = Mapping[str, object]
EffectHandler = Callable[[EventCtx, ActivePet, EffectParams, str], None]

STAT_TO_BUFF_IDX = {
    "atk": 0,
    "def": 1,
    "speed": 2,
    "spatk": 3,
    "spdef": 4,
}


def log_effect(ctx: EventCtx, actor: ActivePet, action: str, detail: dict) -> None:
    record_event(ctx.state, BattleEvent(ctx.state.turn_number, actor.persistent.name, action, detail))


def heal_hp(pet: ActivePet, amount: int) -> None:
    if amount > 0:
        pet.current_hp = min(pet.max_hp, pet.current_hp + amount)


def apply_buff(pet: ActivePet, params: EffectParams, sign: int) -> None:
    buff = params.get("buff", params)
    for key, value in dict(buff).items():
        idx = STAT_TO_BUFF_IDX.get(str(key))
        if idx is None:
            continue
        step = round(abs(float(value)) / 0.10)
        pet.set_buff(idx, clamp_stage(pet.get_buff(idx) + sign * step))


def add_status(
    pet: ActivePet,
    status: StatusType,
    flag: StatusFlag,
    stacks: int,
    *,
    immune: bool = True,
) -> None:
    if stacks <= 0:
        return
    if immune and pet.is_immune_to(flag):
        return
    pet.status_flags |= flag
    pet.set_status_count(status, pet.get_status_count(status) + stacks)


def dispel_positive_buffs(pet: ActivePet) -> None:
    for idx in range(5):
        if pet.get_buff(idx) > 0:
            pet.set_buff(idx, 0)


def team_of(ctx: EventCtx, pet: ActivePet) -> str:
    return "a" if pet in ctx.state.team_a else "b"


def add_meteor_mark(ctx: EventCtx, target: ActivePet | None, stacks: int) -> None:
    if target is None or stacks <= 0:
        return
    if target in ctx.state.team_a:
        ctx.state.marks_a = _set_mark(ctx.state.marks_a, MarkIdx.METEOR, _unpack_mark(ctx.state.marks_a, MarkIdx.METEOR) + stacks)
    else:
        ctx.state.marks_b = _set_mark(ctx.state.marks_b, MarkIdx.METEOR, _unpack_mark(ctx.state.marks_b, MarkIdx.METEOR) + stacks)


def force_switch(ctx: EventCtx, actor: ActivePet) -> None:
    team_id = team_of(ctx, actor)
    team = ctx.state.team_a if team_id == "a" else ctx.state.team_b
    active = ctx.state.active_a if team_id == "a" else ctx.state.active_b
    choices = [i for i, pet in enumerate(team) if i != active and not pet.is_fainted]
    if not choices:
        return
    if team_id == "a":
        ctx.state.active_a = choices[0]
    else:
        ctx.state.active_b = choices[0]


def set_weather(ctx: EventCtx, raw: str, turns: int) -> None:
    weather = {
        "rain": WeatherType.RAIN,
        "sandstorm": WeatherType.SANDSTORM,
        "snow": WeatherType.SNOW,
        "hail": WeatherType.SNOW,
    }.get(raw)
    if weather is None:
        return
    ctx.state.weather_type = weather
    ctx.state.weather_turns = max(1, min(15, turns))


def apply_permanent_skill_mod(ctx: EventCtx, params: EffectParams) -> None:
    skill = ctx.skill
    if not skill:
        return
    target = params.get("target")
    delta = int(params.get("delta", 0))
    if target == "hit_count":
        skill.hit_count = max(1, skill.hit_count + delta)
    elif target == "power":
        skill.power = max(0, skill.power + delta)
