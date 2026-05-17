"""Fixed-kernel effect op table over integer effect rows."""

from __future__ import annotations

from roco.engine.effect_model import EffectTag, Timing
from roco.engine.packing import MarkIdx, _set_mark, _unpack_mark

ROW_TAG = 0
ROW_TIMING = 1
ROW_TARGET = 2
ROW_FLAGS = 3
ROW_COND = 4
ROW_ARG0 = 5
ROW_ARG1 = 6
ROW_ARG2 = 7
ROW_ARG3 = 8
COND_NONE = 0
BPS = 10000
TARGET_SELF = 1
TARGET_ALLY = 3
TARGET_TEAM = 4


class StageCtx:
    __slots__ = (
        "actor_side",
        "actor_slot",
        "target_side",
        "target_slot",
        "skill_id",
        "power",
        "hit_count",
        "power_bps",
        "damage_bps",
        "heal_bps",
        "flat_damage",
        "burn_stacks",
        "poison_stacks",
        "freeze_stacks",
        "leech_stacks",
        "weather",
        "weather_turns",
        "mark_self",
        "mark_enemy",
        "clear_self_marks",
        "clear_enemy_marks",
        "cancelled",
    )

    def __init__(self) -> None:
        self.actor_side = 0
        self.actor_slot = 0
        self.target_side = 0
        self.target_slot = 0
        self.skill_id = 0
        self.power = 0
        self.hit_count = 1
        self.power_bps = BPS
        self.damage_bps = BPS
        self.heal_bps = BPS
        self.flat_damage = 0
        self.burn_stacks = 0
        self.poison_stacks = 0
        self.freeze_stacks = 0
        self.leech_stacks = 0
        self.weather = 0
        self.weather_turns = 0
        self.mark_self = 0
        self.mark_enemy = 0
        self.clear_self_marks = 0
        self.clear_enemy_marks = 0
        self.cancelled = 0

    def reset(self, actor_side: int, actor_slot: int, target_side: int, target_slot: int, skill_id: int) -> None:
        self.actor_side = actor_side
        self.actor_slot = actor_slot
        self.target_side = target_side
        self.target_slot = target_slot
        self.skill_id = skill_id
        self.power = 0
        self.hit_count = 1
        self.power_bps = BPS
        self.damage_bps = BPS
        self.heal_bps = BPS
        self.flat_damage = 0
        self.burn_stacks = 0
        self.poison_stacks = 0
        self.freeze_stacks = 0
        self.leech_stacks = 0
        self.weather = 0
        self.weather_turns = 0
        self.mark_self = 0
        self.mark_enemy = 0
        self.clear_self_marks = 0
        self.clear_enemy_marks = 0
        self.cancelled = 0


def _op_unsupported(ctx: StageCtx, row: tuple[int, ...]) -> None:
    raise NotImplementedError(row[ROW_TAG])


def _op_damage(ctx: StageCtx, row: tuple[int, ...]) -> None:
    if row[ROW_ARG0] > 0:
        ctx.power = row[ROW_ARG0]
    if row[ROW_ARG1] > 0:
        ctx.hit_count = row[ROW_ARG1]


def _noop(ctx: StageCtx, row: tuple[int, ...]) -> None:
    return


def _op_burn(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.burn_stacks += row[ROW_ARG0]


def _op_poison(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.poison_stacks += row[ROW_ARG0]


def _op_freeze(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.freeze_stacks += row[ROW_ARG0]


def _op_leech(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.leech_stacks += row[ROW_ARG0]


def _op_weather(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.weather = row[ROW_ARG0]
    ctx.weather_turns = row[ROW_ARG1]


def _mark_add(packed: int, idx: MarkIdx, stacks: int) -> int:
    return _set_mark(packed, idx, min(15, _unpack_mark(packed, idx) + stacks))


def _op_mark(ctx: StageCtx, row: tuple[int, ...], idx: MarkIdx) -> None:
    stacks = row[ROW_ARG0]
    if stacks <= 0:
        return
    if row[ROW_TARGET] in (TARGET_SELF, TARGET_ALLY, TARGET_TEAM):
        ctx.mark_self = _mark_add(ctx.mark_self, idx, stacks)
    else:
        ctx.mark_enemy = _mark_add(ctx.mark_enemy, idx, stacks)


def _op_moisture_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOISTURE)


def _op_dragon_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.DRAGON)


def _op_momentum_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.MOMENTUM)


def _op_wind_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.WIND)


def _op_charge_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.CHARGE)


def _op_solar_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SOLAR)


def _op_attack_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.ATTACK)


def _op_slow_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLOW)


def _op_spirit_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SPIRIT)


def _op_meteor_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.METEOR)


def _op_poison_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.POISON)


def _op_thorn_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.THORN)


def _op_sluggish_mark(ctx: StageCtx, row: tuple[int, ...]) -> None:
    _op_mark(ctx, row, MarkIdx.SLUGGISH)


def _op_dispel_enemy_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_enemy_marks = 1


def _op_dispel_marks(ctx: StageCtx, row: tuple[int, ...]) -> None:
    ctx.clear_self_marks = 1
    ctx.clear_enemy_marks = 1


_TABLE = [_op_unsupported] * (max(tag.value for tag in EffectTag) + 1)
_TABLE[EffectTag.DAMAGE.value] = _op_damage
_TABLE[EffectTag.DAMAGE_REDUCTION.value] = _noop
_TABLE[EffectTag.HEAL_HP.value] = _noop
_TABLE[EffectTag.HEAL_ENERGY.value] = _noop
_TABLE[EffectTag.BURN.value] = _op_burn
_TABLE[EffectTag.POISON.value] = _op_poison
_TABLE[EffectTag.FREEZE.value] = _op_freeze
_TABLE[EffectTag.LEECH.value] = _op_leech
_TABLE[EffectTag.WEATHER.value] = _op_weather
_TABLE[EffectTag.MOISTURE_MARK.value] = _op_moisture_mark
_TABLE[EffectTag.DRAGON_MARK.value] = _op_dragon_mark
_TABLE[EffectTag.MOMENTUM_MARK.value] = _op_momentum_mark
_TABLE[EffectTag.WIND_MARK.value] = _op_wind_mark
_TABLE[EffectTag.CHARGE_MARK.value] = _op_charge_mark
_TABLE[EffectTag.SOLAR_MARK.value] = _op_solar_mark
_TABLE[EffectTag.ATTACK_MARK.value] = _op_attack_mark
_TABLE[EffectTag.SLOW_MARK.value] = _op_slow_mark
_TABLE[EffectTag.SPIRIT_MARK.value] = _op_spirit_mark
_TABLE[EffectTag.METEOR_MARK.value] = _op_meteor_mark
_TABLE[EffectTag.POISON_MARK.value] = _op_poison_mark
_TABLE[EffectTag.THORN_MARK.value] = _op_thorn_mark
_TABLE[EffectTag.SLUGGISH_MARK.value] = _op_sluggish_mark
_TABLE[EffectTag.DISPEL_ENEMY_MARKS.value] = _op_dispel_enemy_marks
_TABLE[EffectTag.DISPEL_MARKS.value] = _op_dispel_marks
OP_TABLE = tuple(_TABLE)
KERNEL_SUPPORTED_TAGS = tuple(
    idx for idx, op in enumerate(OP_TABLE)
    if op is not _op_unsupported
)


def run_skill_timing(effect_rows: tuple[tuple[int, ...], ...], effect_range: tuple[int, int], timing: int, ctx: StageCtx) -> None:
    start, end = effect_range
    for idx in range(start, end):
        row = effect_rows[idx]
        if row[ROW_TIMING] == timing and row[ROW_COND] == COND_NONE:
            OP_TABLE[row[ROW_TAG]](ctx, row)


TIMING_CALC_DAMAGE = Timing.CALC_DAMAGE.value
TIMING_AFTER_MOVE = Timing.AFTER_MOVE.value
