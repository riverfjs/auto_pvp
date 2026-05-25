"""Runtime triggers for pak active buffs that carry response BUFFBASE rows."""

from __future__ import annotations

from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.common.enums import SkillCategory, StatusType
from roco.common.packing import MarkIdx, _merge_buff_delta
from roco.engine.kernel.model.active_buffs import active_buff_id, iter_active_buffs
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.ops.marks import op_meteor_mark, op_thorn_mark
from roco.engine.kernel.core.rows import TARGET_ENEMY, TARGET_SELF
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.engine.kernel.model.state import KernelState, side
from roco.generated.pak.buff_defs import BUFF_BASE_IDS, BUFF_REDUCE_RULES, BUFF_TYPE as BUFF_KIND
from roco.generated.pak.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.generated.pak.effect_params import EFFECT_ORDER, EFFECT_PARAMS
from roco.generated.static.lua_enums import BUFF_TYPE, EFFECT_TYPE

_ATTR_CHANGE_STAT_CODES = frozenset((6, 29, 30, 31, 32, 33, 34, 35, 36))
_RESPONSE_METADATA_PARAMS = (0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0)


def _buff_type(symbol: str) -> int:
    return int(BUFF_TYPE[symbol])


def _effect_type(symbol: str) -> int:
    return int(EFFECT_TYPE[symbol])


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
        if _is_response_metadata_row(order, params):
            continue
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
    if _param_int(params, 7) != 0:
        return False
    target = TARGET_ENEMY if _param_int(params, 4) == -1 else TARGET_SELF
    tail_flag = _param_int(params, 8)
    if tail_flag == 0:
        return all(_ref_supported(ref_id, target) for ref_id in _as_int_tuple(params[6]))
    if tail_flag == 1:
        return all(_tail_flag_ref_supported(ref_id, target) for ref_id in _as_int_tuple(params[6]))
    return False


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
    if _purifies_regular_marks(ref_id):
        return True
    if _inert_response_ref(ref_id):
        return True
    if _force_switch_ref(ref_id):
        return True
    if _energy_delta_supported(ref_id, target):
        return True
    return bool(_buff_delta(ref_id))


def _tail_flag_ref_supported(ref_id: int, target: int) -> bool:
    del target
    if _mark_type(ref_id) is not None:
        return True
    return bool(_buff_delta(ref_id))


def _apply_response_ref(ctx: StageCtx, ref_id: int, target: int) -> None:
    status = _status_type(ref_id)
    if status == StatusType.POISON:
        ctx.poison_stacks += 1
        return
    if status == StatusType.BURN:
        ctx.burn_stacks += 1
        return
    if status == StatusType.FREEZE:
        ctx.freeze_stacks += 1
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
    if _purifies_regular_marks(ref_id):
        if target == TARGET_SELF:
            ctx.clear_self_marks = 1
        else:
            ctx.clear_enemy_marks = 1
        return
    if _inert_response_ref(ref_id):
        return
    if _force_switch_ref(ref_id):
        if target == TARGET_SELF:
            ctx.force_switch = 1
        else:
            ctx.force_enemy_switch = 1
        return
    energy_delta = _energy_delta(ref_id)
    if energy_delta is not None:
        if target == TARGET_SELF and energy_delta > 0:
            ctx.heal_energy += energy_delta
            return
        if target == TARGET_ENEMY and energy_delta < 0:
            ctx.enemy_lose_energy += abs(energy_delta)
            return
    packed = _buff_delta(ref_id)
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
    if any(order == _buff_type("BFT_FREEZE") and tuple(params) == (1, 500, 0, 50) for _base_id, order, params in rows):
        return StatusType.FREEZE
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


def _purifies_regular_marks(ref_id: int) -> bool:
    rows = _base_rows(ref_id)
    if len(rows) == 1 and rows[0][1] == _buff_type("BFT_IMMUNE"):
        params = rows[0][2]
        if len(params) >= 2 and _param_int(params, 0) == 3:
            effect_ids = _as_int_tuple(params[1])
            return len(effect_ids) == 1 and _effect_purifies_regular_marks(effect_ids[0])
    return _effect_purifies_regular_marks(ref_id)


def _effect_purifies_regular_marks(effect_id: int) -> bool:
    return _effect_purify_refs_match(effect_id, _regular_mark_refs)


def _effect_purifies_zero_delta_sentinels(effect_id: int) -> bool:
    return _effect_purify_refs_match(effect_id, _zero_delta_refs)


def _effect_purify_refs_match(effect_id: int, predicate) -> bool:
    if EFFECT_ORDER.get(effect_id) != _effect_type("ET_PURIFY"):
        return False
    params = EFFECT_PARAMS.get(effect_id) or ()
    if len(params) < 5:
        return False
    if _param_int(params, 0) != 3 or _param_int(params, 2) != 99:
        return False
    if _param_int(params, 3) != 99 or _param_int(params, 4) != 0:
        return False
    refs = _as_int_tuple(params[1])
    return bool(refs) and predicate(refs)


def _regular_mark_refs(ref_ids: tuple[int, ...]) -> bool:
    return all(int(BUFF_KIND.get(ref_id, 0) or 0) == 4 for ref_id in ref_ids)


def _zero_delta_refs(ref_ids: tuple[int, ...]) -> bool:
    return all(_zero_stat_delta_buff(ref_id) for ref_id in ref_ids)


def _inert_response_ref(ref_id: int) -> bool:
    return _zero_stat_delta_buff(ref_id) or _buff_after_skill_purifies_zero_delta_sentinels(ref_id)


def _force_switch_ref(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != _buff_type("BFT_PET_TRANSE"):
        return False
    _base_id, _order, params = rows[0]
    return len(params) >= 2 and _param_int(params, 1) == 1 and _params_all_zero(params[2:])


def _energy_delta_supported(effect_id: int, target: int) -> bool:
    delta = _energy_delta(effect_id)
    return (target == TARGET_SELF and delta is not None and delta > 0) or (
        target == TARGET_ENEMY and delta is not None and delta < 0
    )


def _energy_delta(effect_id: int) -> int | None:
    if EFFECT_ORDER.get(effect_id) != _effect_type("ET_CHANGE_ENERGY"):
        return None
    params = EFFECT_PARAMS.get(effect_id) or ()
    if len(params) < 3 or not _params_all_zero(params[1:]):
        return None
    direct = _param_int(params, 0)
    return direct if direct else None


def _buff_after_skill_purifies_zero_delta_sentinels(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != _buff_type("BFT_BUFF_AFTER_SKILL"):
        return False
    _base_id, _order, params = rows[0]
    if len(params) < 7:
        return False
    if not _params_all_zero(params[:4]) or _param_int(params, 5) != 0:
        return False
    effect_ids = _as_int_tuple(params[4])
    return len(effect_ids) == 1 and _effect_purifies_zero_delta_sentinels(effect_ids[0])


def _zero_stat_delta_buff(buff_id: int) -> bool:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != _buff_type("BFT_ATTR_CHANGE"):
        return False
    _base_id, _order, params = rows[0]
    return len(params) >= 3 and _param_int(params, 0) in _ATTR_CHANGE_STAT_CODES and _params_all_zero(params[1:])


def _is_response_metadata_row(order: object, params: tuple) -> bool:
    return order == _buff_type("BFT_INC_DAM_BY_SKILL") and params == _RESPONSE_METADATA_PARAMS


def _buff_delta(buff_id: int) -> int:
    return pack_buff_delta_from_base_ids(BUFF_BASE_IDS.get(buff_id) or ())


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


def _params_all_zero(values: tuple) -> bool:
    return all(all(raw == 0 for raw in _as_int_tuple(value)) for value in values)


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
