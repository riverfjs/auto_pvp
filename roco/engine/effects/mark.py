"""Concrete mark primitive ops backed by packed mark fields."""

from __future__ import annotations

from roco.engine.effect_model import EffectTag
from roco.engine.enums import StatusFlag, StatusType
from roco.engine.events import EventCtx
from roco.engine.packing import MarkIdx, _set_mark, _unpack_mark
from roco.engine.state import ActivePet

from .common import EffectOp, EffectParams, add_status, heal_hp, team_of


ALL_MARKS = tuple(MarkIdx)
POSITIVE_MARK_MASK = sum(0xF << (idx.value * 4) for idx in (
    MarkIdx.MOISTURE,
    MarkIdx.DRAGON,
    MarkIdx.MOMENTUM,
    MarkIdx.WIND,
    MarkIdx.CHARGE,
    MarkIdx.SOLAR,
    MarkIdx.ATTACK,
    MarkIdx.SLUGGISH,
))
NEGATIVE_MARK_MASK = sum(0xF << (idx.value * 4) for idx in (
    MarkIdx.SLOW,
    MarkIdx.SPIRIT,
    MarkIdx.METEOR,
    MarkIdx.POISON,
    MarkIdx.THORN,
))


def _is_positive(idx: MarkIdx) -> bool:
    return bool(POSITIVE_MARK_MASK & (0xF << (idx.value * 4)))


def _same_polarity_mask(idx: MarkIdx) -> int:
    return POSITIVE_MARK_MASK if _is_positive(idx) else NEGATIVE_MARK_MASK


def _team_marks(ctx: EventCtx, team: str) -> int:
    return ctx.state.marks_a if team == "a" else ctx.state.marks_b


def _set_team_marks(ctx: EventCtx, team: str, marks: int) -> None:
    if team == "a":
        ctx.state.marks_a = marks
    else:
        ctx.state.marks_b = marks


def _opponent(team: str) -> str:
    return "b" if team == "a" else "a"


def _target_team(ctx: EventCtx, actor: ActivePet, params: EffectParams) -> str:
    raw = str(params.get("target", "enemy"))
    actor_team = team_of(ctx, actor)
    if raw in {"self", "ally", "own"}:
        return actor_team
    if raw == "target" and ctx.target is not None:
        return team_of(ctx, ctx.target)
    return _opponent(actor_team)


def _active_on_team(ctx: EventCtx, team: str) -> ActivePet:
    if team == "a":
        return ctx.state.team_a[ctx.state.active_a]
    return ctx.state.team_b[ctx.state.active_b]


def _clear_other_same_polarity(marks: int, idx: MarkIdx) -> int:
    keep = 0xF << (idx.value * 4)
    clear = _same_polarity_mask(idx) & ~keep
    return marks & ~clear


def _add_mark_to_team(ctx: EventCtx, team: str, idx: MarkIdx, stacks: int) -> None:
    if stacks <= 0:
        return
    marks = _clear_other_same_polarity(_team_marks(ctx, team), idx)
    _set_team_marks(ctx, team, _set_mark(marks, idx, min(15, _unpack_mark(marks, idx) + stacks)))


def _make_mark_op(idx: MarkIdx) -> EffectOp:
    def op(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
        _add_mark_to_team(ctx, _target_team(ctx, actor, params), idx, int(params.get("stacks", 1)))

    return op


def _mark_total(marks: int) -> int:
    total = 0
    for idx in ALL_MARKS:
        total += _unpack_mark(marks, idx)
    return total


def _remove_mark_stacks(marks: int, stacks: int) -> int:
    remaining = max(0, stacks)
    while remaining > 0:
        best_idx = MarkIdx.MOISTURE
        best = 0
        for idx in ALL_MARKS:
            count = _unpack_mark(marks, idx)
            if count > best:
                best = count
                best_idx = idx
        if best <= 0:
            return marks
        marks = _set_mark(marks, best_idx, best - 1)
        remaining -= 1
    return marks


def h_dispel_enemy_marks(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    team = _opponent(team_of(ctx, actor))
    stacks = int(params.get("stacks", 0))
    _set_team_marks(ctx, team, _remove_mark_stacks(_team_marks(ctx, team), stacks) if stacks > 0 else 0)


def h_dispel_marks(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if params.get("condition") == "not_blocked" and ctx.countered:
        return
    ctx.state.marks_a = 0
    ctx.state.marks_b = 0


def h_convert_marks_to_burn(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    team = _opponent(team_of(ctx, actor))
    marks = _team_marks(ctx, team)
    total = _mark_total(marks)
    if total <= 0:
        return
    _set_team_marks(ctx, team, 0)
    add_status(_active_on_team(ctx, team), StatusType.BURN, StatusFlag.BURN, total * int(params.get("ratio", 3)), immune=False)


def h_dispel_marks_to_burn(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    total = _mark_total(ctx.state.marks_a) + _mark_total(ctx.state.marks_b)
    if total <= 0:
        return
    ctx.state.marks_a = 0
    ctx.state.marks_b = 0
    target = ctx.target or _active_on_team(ctx, _opponent(team_of(ctx, actor)))
    add_status(target, StatusType.BURN, StatusFlag.BURN, total * int(params.get("burn_per_mark", 5)), immune=False)


def h_consume_marks_heal(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    team = _opponent(team_of(ctx, actor))
    marks = _team_marks(ctx, team)
    total = _mark_total(marks)
    if total <= 0:
        return
    _set_team_marks(ctx, team, 0)
    heal_hp(actor, int(actor.max_hp * float(params.get("heal_pct_per_mark", 0.1)) * total))


def h_marks_to_meteor(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    team = _opponent(team_of(ctx, actor))
    marks = _team_marks(ctx, team)
    total = _mark_total(marks)
    if total <= 0:
        return
    _set_team_marks(ctx, team, 0)
    _add_mark_to_team(ctx, team, MarkIdx.METEOR, total)


def h_steal_marks(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    own = team_of(ctx, actor)
    enemy = _opponent(own)
    stolen = _team_marks(ctx, enemy)
    if stolen <= 0:
        return
    _set_team_marks(ctx, own, stolen)
    _set_team_marks(ctx, enemy, 0)


def h_energy_cost_per_enemy_mark(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    total = _mark_total(_team_marks(ctx, _opponent(team_of(ctx, actor))))
    if total > 0:
        ctx.cost = max(0, ctx.cost - total)


def h_stat_scale_meteor_marks_per_turn(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    _add_mark_to_team(ctx, _opponent(team_of(ctx, actor)), MarkIdx.METEOR, int(params.get("marks_per_turn", 2)))


def h_mark_power_per_meteor(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    stacks = _unpack_mark(_team_marks(ctx, _opponent(team_of(ctx, actor))), MarkIdx.METEOR)
    if stacks > 0:
        ctx.power_mod += float(params.get("bonus_pct_per_mark", 0.15)) * stacks


def h_mark_freeze_to_meteor(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    target = ctx.target
    if target is None:
        return
    stacks = target.get_status_count(StatusType.FREEZE)
    if stacks > 0:
        _add_mark_to_team(ctx, team_of(ctx, target), MarkIdx.METEOR, stacks)


def h_mark_stack_no_replace(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    return


def h_mark_stack_debuffs(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    return


OP_ROWS: tuple[tuple[EffectTag, EffectOp], ...] = (
    (EffectTag.POISON_MARK, _make_mark_op(MarkIdx.POISON)),
    (EffectTag.MOISTURE_MARK, _make_mark_op(MarkIdx.MOISTURE)),
    (EffectTag.DRAGON_MARK, _make_mark_op(MarkIdx.DRAGON)),
    (EffectTag.WIND_MARK, _make_mark_op(MarkIdx.WIND)),
    (EffectTag.CHARGE_MARK, _make_mark_op(MarkIdx.CHARGE)),
    (EffectTag.SOLAR_MARK, _make_mark_op(MarkIdx.SOLAR)),
    (EffectTag.ATTACK_MARK, _make_mark_op(MarkIdx.ATTACK)),
    (EffectTag.SLOW_MARK, _make_mark_op(MarkIdx.SLOW)),
    (EffectTag.SLUGGISH_MARK, _make_mark_op(MarkIdx.SLUGGISH)),
    (EffectTag.SPIRIT_MARK, _make_mark_op(MarkIdx.SPIRIT)),
    (EffectTag.METEOR_MARK, _make_mark_op(MarkIdx.METEOR)),
    (EffectTag.THORN_MARK, _make_mark_op(MarkIdx.THORN)),
    (EffectTag.MOMENTUM_MARK, _make_mark_op(MarkIdx.MOMENTUM)),
    (EffectTag.DISPEL_ENEMY_MARKS, h_dispel_enemy_marks),
    (EffectTag.CONVERT_MARKS_TO_BURN, h_convert_marks_to_burn),
    (EffectTag.DISPEL_MARKS_TO_BURN, h_dispel_marks_to_burn),
    (EffectTag.CONSUME_MARKS_HEAL, h_consume_marks_heal),
    (EffectTag.MARKS_TO_METEOR, h_marks_to_meteor),
    (EffectTag.STEAL_MARKS, h_steal_marks),
    (EffectTag.ENERGY_COST_PER_ENEMY_MARK, h_energy_cost_per_enemy_mark),
    (EffectTag.DISPEL_MARKS, h_dispel_marks),
    (EffectTag.STAT_SCALE_METEOR_MARKS_PER_TURN, h_stat_scale_meteor_marks_per_turn),
    (EffectTag.MARK_POWER_PER_METEOR, h_mark_power_per_meteor),
    (EffectTag.MARK_FREEZE_TO_METEOR, h_mark_freeze_to_meteor),
    (EffectTag.MARK_STACK_NO_REPLACE, h_mark_stack_no_replace),
    (EffectTag.MARK_STACK_DEBUFFS, h_mark_stack_debuffs),
)
