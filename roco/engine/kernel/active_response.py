"""Runtime triggers for pak active buffs that carry response BUFFBASE rows."""

from __future__ import annotations

from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.common.enums import SkillCategory, StatusType
from roco.common.packing import MarkIdx, _merge_buff_delta
from roco.engine.kernel.active_buffs import active_buff_id, iter_active_buffs
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_marks import op_meteor_mark, op_thorn_mark
from roco.engine.kernel.op_rows import TARGET_ENEMY, TARGET_SELF
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.engine.kernel.state import KernelState, side
from roco.generated.buff_defs import BUFF_BASE_IDS, BUFF_REDUCE_RULES
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.generated.static.lua_enums import BUFF_TYPE


def _buff_type(symbol: str) -> int:
    return int(BUFF_TYPE[symbol])


def after_attack_response_supported(buff_id: int) -> bool:
    return _response_duration_args(buff_id) is not None and bool(_response_rows(buff_id))


def after_attack_response_duration_args(buff_id: int) -> tuple[int, int, int]:
    args = _response_duration_args(buff_id)
    if args is None:
        raise RuntimeError(f"BUFF_CONF[{buff_id}] has unsupported active response reduce rules")
    return args


def trigger_after_attack_active_buffs(
    state: KernelState,
    attacker_side_id: int,
    attacker_slot: int,
    defender_side_id: int,
    defender_slot: int,
    skill_category: int,
    damage_dealt: int,
) -> KernelState:
    if damage_dealt <= 0 or skill_category not in (SkillCategory.PHYSICAL.value, SkillCategory.MAGICAL.value):
        return state
    defender_side = side(state, defender_side_id)
    defender = defender_side.pets[defender_slot]
    if defender.fainted or defender.active_buffs == 0:
        return state
    ctx = StageCtx()
    ctx.reset(defender_side_id, defender_slot, attacker_side_id, attacker_slot, 0)
    ctx.skill_category = skill_category
    fired = False
    for _slot_idx, lane in iter_active_buffs(defender.active_buffs):
        buff_id = active_buff_id(lane)
        rows = _response_rows(buff_id)
        if not rows:
            continue
        for _base_id, params in rows:
            _apply_response_params(ctx, params)
            fired = True
    if not fired:
        return state
    return apply_after_move(state, defender_side_id, defender_slot, attacker_side_id, attacker_slot, ctx)


def _response_rows(buff_id: int) -> tuple[tuple[int, tuple], ...]:
    if _response_duration_args(buff_id) is None:
        return ()
    rows: list[tuple[int, tuple]] = []
    for base_id in BUFF_BASE_IDS.get(buff_id) or ():
        order = BUFFBASE_ORDER.get(base_id)
        params = BUFFBASE_PARAMS.get(base_id) or ()
        if order != _buff_type("BFT_CAST_SKILL_AFTER_ATTACK"):
            return ()
        if not _response_params_supported(params):
            return ()
        rows.append((int(base_id), params))
    return tuple(rows)


def _response_duration_args(buff_id: int) -> tuple[int, int, int] | None:
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if len(rules) != 1:
        return None
    reduce_type, params = rules[0]
    p0 = int(params[0]) if len(params) > 0 else 0
    p1 = int(params[1]) if len(params) > 1 else 0
    if int(reduce_type) == 13 and p0 == 999 and p1 == 0:
        return (13, p0, p1)
    if int(reduce_type) == 2 and p0 > 0:
        return (2, p0, p1)
    return None


def _response_params_supported(params: tuple) -> bool:
    if len(params) < 9:
        return False
    if _as_int_tuple(params[0]) != (0,) or set(_as_int_tuple(params[1])) != {2, 3}:
        return False
    if _param_int(params, 2) != 0 or _param_int(params, 3) != 0:
        return False
    if _param_int(params, 4) not in (-1, 0) or _param_int(params, 5) != 10000:
        return False
    if _param_int(params, 7) != 0 or _param_int(params, 8) != 0:
        return False
    target = TARGET_ENEMY if _param_int(params, 4) == -1 else TARGET_SELF
    return all(_ref_supported(ref_id, target) for ref_id in _as_int_tuple(params[6]))


def _apply_response_params(ctx: StageCtx, params: tuple) -> None:
    target = TARGET_ENEMY if _param_int(params, 4) == -1 else TARGET_SELF
    for ref_id in _as_int_tuple(params[6]):
        _apply_response_ref(ctx, ref_id, target)


def _ref_supported(ref_id: int, target: int) -> bool:
    if _status_type(ref_id) is not None:
        return target == TARGET_ENEMY
    if _mark_type(ref_id) is not None:
        return True
    if _hit_delta(ref_id) is not None:
        return True
    return bool(pack_buff_delta_from_base_ids(BUFF_BASE_IDS.get(ref_id) or ()))


def _apply_response_ref(ctx: StageCtx, ref_id: int, target: int) -> None:
    status = _status_type(ref_id)
    if status == StatusType.POISON:
        ctx.poison_stacks += 1
        return
    if status == StatusType.BURN:
        ctx.burn_stacks += 1
        return
    mark = _mark_type(ref_id)
    if mark == MarkIdx.METEOR:
        op_meteor_mark(ctx, (0, 0, target, 10000, 0, 1, 0, 0, 0))
        return
    if mark == MarkIdx.THORN:
        op_thorn_mark(ctx, (0, 0, target, 10000, 0, 1, 0, 0, 0))
        return
    hit_delta = _hit_delta(ref_id)
    if hit_delta is not None:
        if target == TARGET_SELF:
            ctx.actor_hit_delta += hit_delta
        else:
            ctx.enemy_hit_delta += hit_delta
        return
    packed = pack_buff_delta_from_base_ids(BUFF_BASE_IDS.get(ref_id) or ())
    if packed:
        if target == TARGET_SELF:
            ctx.self_buff = _merge_buff_delta(ctx.self_buff, packed)
        else:
            ctx.enemy_buff = _merge_buff_delta(ctx.enemy_buff, packed)


def _status_type(buff_id: int) -> StatusType | None:
    rows = _base_rows(buff_id)
    if any(order == _buff_type("BFT_DAM") and _param_int(params, 4) == 12 for _base_id, order, params in rows):
        return StatusType.POISON
    if any(order == _buff_type("BFT_DAM") and _param_int(params, 4) == 4 for _base_id, order, params in rows):
        return StatusType.BURN
    return None


def _mark_type(buff_id: int) -> MarkIdx | None:
    rows = _base_rows(buff_id)
    if any(order == _buff_type("BFT_NINETY_FOUR") for _base_id, order, _params in rows):
        return MarkIdx.METEOR
    if any(order == _buff_type("BFT_SPIKES") and _param_int(params, 0) == 1001005 for _base_id, order, params in rows):
        return MarkIdx.THORN
    return None


def _hit_delta(buff_id: int) -> int | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != _buff_type("BFT_MULTIPLE_NUM"):
        return None
    _base_id, _order, params = rows[0]
    if len(params) < 3:
        return None
    if _param_int(params, 1) != 0 or _param_int(params, 2) != 0:
        return None
    amount = _param_int(params, 0)
    return amount if amount else None


def _base_rows(buff_id: int) -> tuple[tuple[int, int, tuple], ...]:
    rows: list[tuple[int, int, tuple]] = []
    for base_id in BUFF_BASE_IDS.get(buff_id) or ():
        rows.append((int(base_id), int(BUFFBASE_ORDER.get(base_id, 0) or 0), BUFFBASE_PARAMS.get(base_id) or ()))
    return tuple(rows)


def _as_int_tuple(value: object) -> tuple[int, ...]:
    values = value if isinstance(value, (tuple, list)) else (value,)
    out: list[int] = []
    for raw in values:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _param_int(params: tuple, index: int, default: int = 0) -> int:
    if index >= len(params):
        return default
    value = params[index]
    if isinstance(value, tuple):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
