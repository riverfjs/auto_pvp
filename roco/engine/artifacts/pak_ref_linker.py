"""Engine linker for exact pak ``BUFF_CONF`` / ``EFFECT_CONF`` references."""

from __future__ import annotations

from roco.common.buffbase import pack_buff_delta_from_base_ids
from roco.common.entry_sources import (
    ENTRY_SOURCE_COUNTER,
    ENTRY_SOURCE_DEFENSE,
    ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE,
    ENTRY_SOURCE_ENEMY_SWITCH,
    ENTRY_SOURCE_EQUIPPED_ELEMENT,
    ENTRY_SOURCE_STATUS,
    ENTRY_SOURCE_USED_ELEMENT,
    entry_source_code,
)
from roco.common.enums import Element
from roco.common.primitive_keys import BUFF_REF_PREFIX, EFFECT_REF_PREFIX, strip_prefix
from roco.engine.artifacts.linked_op import LinkGap, LinkGapError, LinkedOp
from roco.engine.kernel.op_rows import TIMING_HOOK_BEFORE_MOVE, TIMING_PAK_BEFORE_HURT, TIMING_PAK_SDT
from roco.generated.buff_defs import BUFF_BASE_IDS, BUFF_REDUCE_RULES, BUFF_TYPE as BUFF_KIND
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS
from roco.generated.effect_params import EFFECT_ORDER, EFFECT_PARAMS, EFFECT_TYPE
from roco.generated.skill_dam_types import SKILL_DAM_TYPE_TO_ELEMENT
from roco.generated.static.lua_enums import BUFF_TYPE, EFFECT_TYPE as EFFECT_TYPE_ENUM
from roco.generated.weather_table import PAK_WEATHER_DEFAULT_TURNS, PAK_WEATHER_TYPE_TO_KERNEL


COUNT_FAINTED_ALLY = -1

BFT_ABSORB = int(BUFF_TYPE["BFT_ABSORB"])
BFT_ASSIGN = int(BUFF_TYPE["BFT_ASSIGN"])
BFT_ATTR_CHANGE = int(BUFF_TYPE["BFT_ATTR_CHANGE"])
BFT_BUFF_AFTER_SKILL = int(BUFF_TYPE["BFT_BUFF_AFTER_SKILL"])
BFT_CHANGE_SKILL_ENERGY_COST = int(BUFF_TYPE["BFT_CHANGE_SKILL_ENERGY_COST"])
BFT_CHECK_BUFF_LAYER = int(BUFF_TYPE["BFT_CHECK_BUFF_LAYER"])
BFT_DAM = int(BUFF_TYPE["BFT_DAM"])
BFT_DAMNUM_CHANGE = int(BUFF_TYPE["BFT_DAMNUM_CHANGE"])
BFT_IMMUNE = int(BUFF_TYPE["BFT_IMMUNE"])
BFT_INC_DAM_BY_ATTACK_FIRST = int(BUFF_TYPE["BFT_INC_DAM_BY_ATTACK_FIRST"])
BFT_INC_DAM_BY_SKILL = int(BUFF_TYPE["BFT_INC_DAM_BY_SKILL"])
BFT_MULTIPLE_NUM = int(BUFF_TYPE["BFT_MULTIPLE_NUM"])
BFT_NINETY_EIGHT = int(BUFF_TYPE["BFT_NINETY_EIGHT"])
BFT_NINETY_FOUR = int(BUFF_TYPE["BFT_NINETY_FOUR"])
BFT_NINETY_ONE = int(BUFF_TYPE["BFT_NINETY_ONE"])
BFT_NINETY_THREE = int(BUFF_TYPE["BFT_NINETY_THREE"])
BFT_O_EIGHT = int(BUFF_TYPE["BFT_O_EIGHT"])
BFT_O_FIFTEEN = int(BUFF_TYPE["BFT_O_FIFTEEN"])
BFT_O_FORTYSIX = int(BUFF_TYPE["BFT_O_FORTYSIX"])
BFT_O_T = int(BUFF_TYPE["BFT_O_T"])
BFT_O_TWO = int(BUFF_TYPE["BFT_O_TWO"])
BFT_SPIKES = int(BUFF_TYPE["BFT_SPIKES"])
BFT_STRENGTHEN_THE_SKILL = int(BUFF_TYPE["BFT_STRENGTHEN_THE_SKILL"])

ET_BUFF_BY_EQUIP_SKILL_NUM = int(EFFECT_TYPE_ENUM["ET_BUFF_BY_EQUIP_SKILL_NUM"])
ET_BUFF_BY_CHANGE_TIMES = int(EFFECT_TYPE_ENUM["ET_BUFF_BY_CHANGE_TIMES"])
ET_BUFF_BY_PACK_PET_NUM = int(EFFECT_TYPE_ENUM["ET_BUFF_BY_PACK_PET_NUM"])
ET_BUFF_CONVERT = int(EFFECT_TYPE_ENUM["ET_BUFF_CONVERT"])
ET_CHANGE_ENERGY = int(EFFECT_TYPE_ENUM["ET_CHANGE_ENERGY"])
ET_CHANGE_WEATHER = int(EFFECT_TYPE_ENUM["ET_CHANGE_WEATHER"])
ET_COPY_BUFF = int(EFFECT_TYPE_ENUM["ET_COPY_BUFF"])
ET_COUNTER = int(EFFECT_TYPE_ENUM["ET_COUNTER"])
ET_FAST_SKILL = int(EFFECT_TYPE_ENUM["ET_FAST_SKILL"])
ET_HERO = int(EFFECT_TYPE_ENUM["ET_HERO"])
ET_INLAY = int(EFFECT_TYPE_ENUM["ET_INLAY"])
ET_LIMIT_FIGHT_BY_HP = int(EFFECT_TYPE_ENUM["ET_LIMIT_FIGHT_BY_HP"])
ET_MULTIPLE = int(EFFECT_TYPE_ENUM["ET_MULTIPLE"])
ET_PURIFY = int(EFFECT_TYPE_ENUM["ET_PURIFY"])
ET_RECOVER = int(EFFECT_TYPE_ENUM["ET_RECOVER"])
ET_SKILL_CD = int(EFFECT_TYPE_ENUM["ET_SKILL_CD"])
ET_SUCKBLOOD = int(EFFECT_TYPE_ENUM["ET_SUCKBLOOD"])
ET_SWAP_STAT = int(EFFECT_TYPE_ENUM["ET_SWAP_STAT"])
ET_SWAP_SKILLS = int(EFFECT_TYPE_ENUM["ET_SWAP_SKILLS"])



def link_pak_ref(
    primitive: str,
    timing: int,
    target: int,
    rate: int,
    p0: int,
    p1: int,
    p2: int,
    p3: int,
    *,
    source_name: str,
) -> tuple[LinkedOp, ...] | None:
    buff_ref = strip_prefix(primitive, BUFF_REF_PREFIX)
    if buff_ref is not None:
        try:
            return _link_buff_ref(
                int(buff_ref),
                timing,
                target,
                rate,
                p0,
                p1,
                p2,
                p3,
                source_name=source_name,
            )
        except ValueError as exc:
            raise RuntimeError(f"{source_name!r} produced malformed buff ref {primitive!r}") from exc

    effect_ref = strip_prefix(primitive, EFFECT_REF_PREFIX)
    if effect_ref is not None:
        try:
            return _link_effect_ref(
                int(effect_ref),
                timing,
                target,
                rate,
                p0,
                p1,
                p2,
                p3,
                source_name=source_name,
            )
        except ValueError as exc:
            raise RuntimeError(f"{source_name!r} produced malformed effect ref {primitive!r}") from exc
    return None


def _op(
    op_name: str,
    timing: int,
    target: int,
    rate: int,
    p0: int = 0,
    p1: int = 0,
    p2: int = 0,
    p3: int = 0,
) -> LinkedOp:
    return LinkedOp(op_name, timing, target, rate, int(p0), int(p1), int(p2), int(p3))


def _gap(
    primitive: str,
    reason: str,
    *,
    source_name: str,
    timing: int,
    target: int,
    rate: int,
    effect_id: int | None = None,
    buff_id: int | None = None,
    **params: object,
) -> LinkGapError:
    return LinkGapError(LinkGap(
        primitive=primitive,
        reason=reason,
        source_name=source_name,
        effect_id=effect_id,
        buff_id=buff_id,
        timing=timing,
        target=target,
        rate=rate,
        params=params,
    ))


def _link_ref_id(
    ref_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> tuple[LinkedOp, ...]:
    if ref_id in EFFECT_ORDER:
        return _link_effect_ref(ref_id, timing, target, rate, 0, 0, 0, 0, source_name=source_name)
    if ref_id in BUFF_BASE_IDS:
        return _link_buff_ref(ref_id, timing, target, rate, 0, 0, 0, 0, source_name=source_name)
    raise _gap(
        f"pak_ref:{ref_id}",
        "assigned_ref_not_in_pak",
        source_name=source_name,
        timing=timing,
        target=target,
        rate=rate,
        ref_id=ref_id,
    )


def _link_assign_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> tuple[LinkedOp, ...] | None:
    assign_rows = [
        (base_id, params)
        for base_id, order, params in _base_rows(buff_id)
        if order == BFT_ASSIGN
    ]
    if not assign_rows:
        return None
    linked: list[LinkedOp] = []
    for base_id, params in assign_rows:
        refs = _as_int_tuple(_param(params, 0))
        assign_rate = _param_int(params, 1, 10000)
        target_code = _param_int(params, 2)
        if not refs:
            raise _gap(
                f"buff_ref:{buff_id}",
                "assign_no_refs",
                source_name=source_name,
                timing=timing,
                target=target,
                rate=rate,
                buff_id=buff_id,
                buff_base_id=base_id,
            )
        if assign_rate <= 0:
            raise _gap(
                f"buff_ref:{buff_id}",
                "assign_zero_rate",
                source_name=source_name,
                timing=timing,
                target=target,
                rate=rate,
                buff_id=buff_id,
                buff_base_id=base_id,
                assign_rate=assign_rate,
            )
        if target_code not in (0, 1, 2, 3, 4):
            raise _gap(
                f"buff_ref:{buff_id}",
                "assign_condition_unsupported",
                source_name=source_name,
                timing=timing,
                target=target,
                rate=rate,
                buff_id=buff_id,
                buff_base_id=base_id,
                assigned_refs=refs,
                assign_target_or_condition=target_code,
            )
        child_target = target_code or target
        child_rate = rate * assign_rate // 10000
        for ref_id in refs:
            linked.extend(_link_ref_id(ref_id, timing, child_target, child_rate, source_name=source_name))
    return tuple(linked)


def _link_entry_energy_buff(
    buff_id: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != BFT_O_T:
        return None
    base_id, _order, base_params = rows[0]
    if len(base_params) < 7:
        raise _gap(
            f"buff_ref:{buff_id}",
            "bft_o_t_short_params",
            source_name=source_name,
            timing=TIMING_PAK_SDT,
            target=target,
            rate=rate,
            buff_id=buff_id,
            buff_base_id=base_id,
            base_params=base_params,
        )
    amount = _energy_amount_from_effect_refs(_as_int_tuple(base_params[4]), source_name=source_name)
    source_kind = _param_int(base_params, 6)
    if source_kind == 0:
        element = _skill_dam_type_to_element(_param_int(base_params, 0), source_name=source_name)
        return _op("op_entry_energy_from_element_count", TIMING_PAK_SDT, target, rate, element, amount)
    if source_kind == 1 and _param_int(base_params, 0) == 0:
        return _op("op_entry_energy_from_counter_count", TIMING_PAK_SDT, target, rate, amount)
    raise _gap(
        f"buff_ref:{buff_id}",
        "bft_o_t_source_shape_unsupported",
        source_name=source_name,
        timing=TIMING_PAK_SDT,
        target=target,
        rate=rate,
        buff_id=buff_id,
        buff_base_id=base_id,
        base_params=base_params,
    )


def _link_generic_buff_delta(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    base_ids = tuple(int(v) for v in BUFF_BASE_IDS.get(buff_id) or () if v)
    packed = pack_buff_delta_from_base_ids(base_ids)
    if packed:
        return _op("op_self_buff", timing, target, rate, packed)
    return None


def _link_buff_ref(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    p0: int,
    p1: int,
    p2: int,
    p3: int,
    *,
    source_name: str,
) -> tuple[LinkedOp, ...]:
    if buff_id not in BUFF_BASE_IDS:
        raise _gap(
            f"buff_ref:{buff_id}",
            "buff_id_not_in_pak",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            buff_id=buff_id,
        )

    assigned = _link_assign_buff(buff_id, timing, target, rate, source_name=source_name)
    if assigned is not None:
        return assigned

    stack_count = max(1, p0)
    linked = (
        _link_status_or_mark_buff(buff_id, timing, target, rate, stack_count)
        or _link_zero_energy_auto_switch_buff(buff_id, timing, target, rate)
        or _link_active_immunity_buff(buff_id, timing, target, rate, source_name=source_name)
        or _link_team_skill_hit_count_buff(
            buff_id, timing, target, rate, stack_count, source_name=source_name
        )
        or _link_hit_count_delta_buff(
            buff_id, timing, target, rate, stack_count, source_name=source_name
        )
        or _link_heal_reversal_buff(buff_id, timing, target, rate, source_name=source_name)
        or _link_cute_bench_cost_reduce_buff(buff_id, timing, target, rate, source_name=source_name)
        or _link_conditional_hit_count_buff(buff_id, timing, target, rate, p0, source_name=source_name)
        or _link_transmission_buff(buff_id, timing, target, rate, p0, p1, p2, p3)
        or _link_entry_energy_buff(buff_id, target, rate, source_name=source_name)
        or _link_generic_buff_delta(buff_id, timing, target, rate)
    )
    if linked is not None:
        return (linked,)
    raise _gap(
        f"buff_ref:{buff_id}",
        "buff_shape_unsupported",
        source_name=source_name,
        timing=timing,
        target=target,
        rate=rate,
        buff_id=buff_id,
        base_ids=BUFF_BASE_IDS.get(buff_id) or (),
        base_orders=tuple(BUFFBASE_ORDER.get(base_id) for base_id in BUFF_BASE_IDS.get(buff_id) or ()),
    )


def _link_effect_ref(
    effect_id: int,
    timing: int,
    target: int,
    rate: int,
    p0: int,
    p1: int,
    p2: int,
    p3: int,
    *,
    source_name: str,
) -> tuple[LinkedOp, ...]:
    order = EFFECT_ORDER.get(effect_id)
    if order is None:
        raise _gap(
            f"effect_ref:{effect_id}",
            "effect_id_not_in_pak",
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            effect_id=effect_id,
        )
    params = EFFECT_PARAMS.get(effect_id) or ()
    etype = EFFECT_TYPE.get(effect_id)
    if etype == 2:
        return (_op("op_damage", timing, target, rate, _param_int(params, 2), 0, _param_int(params, 6)),)
    if order == ET_INLAY and p0 > 0 and (p1 or p2 or p3):
        return (_op("op_skill_mod", timing, target, rate, p0, p1, p2, p3),)
    if order == ET_PURIFY:
        linked = _link_effect_purify(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_RECOVER:
        amount = _param_int(params, 1)
        if amount:
            return (_op("op_heal_hp", timing, target, rate, amount),)
    if order == ET_SUCKBLOOD:
        amount = _param_int(params, 0)
        if amount:
            return (_op("op_life_drain", timing, target, rate, amount),)
    if order == ET_CHANGE_ENERGY:
        linked = _link_effect_change_energy(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_CHANGE_WEATHER:
        linked = _link_effect_weather(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_COUNTER:
        response_skill_id = _param_int(params, 0)
        if 7000000 <= response_skill_id < 8000000:
            return (_op("op_install_counter", TIMING_PAK_BEFORE_HURT, target, rate, response_skill_id),)
    if order == ET_MULTIPLE:
        linked = _link_effect_hit_count(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_SKILL_CD:
        turns = _param_int(params, 0)
        if turns > 0 and _param_int(params, 2) == 1 and _param_int(params, 3) == 0:
            return (_op("op_set_self_cooldown", timing, target, rate, turns),)
    if order == ET_FAST_SKILL:
        delta = _param_int(params, 2)
        if delta:
            return (_op("op_priority_next_delta", timing, target, rate, delta),)
    if order == ET_SWAP_STAT:
        mode = _param_int(params, 0)
        if mode == 1:
            return (_op("op_exchange_hp_ratio", timing, target, rate),)
        if mode == 3:
            return (_op("op_transfer_mods", timing, target, rate),)
    if order == ET_SWAP_SKILLS and _param_int(params, 0) == 1:
        return (_op("op_exchange_moves", timing, target, rate),)
    if order == ET_COPY_BUFF:
        linked = _link_effect_copy_buff(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_BUFF_CONVERT:
        linked = _link_effect_buff_convert(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_BUFF_BY_PACK_PET_NUM:
        linked = _link_effect_buff_by_pack_pet_num(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_BUFF_BY_CHANGE_TIMES:
        packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 0)))
        if packed:
            return (_op("op_self_buff", TIMING_PAK_SDT, target, rate, packed),)
    if order == ET_LIMIT_FIGHT_BY_HP:
        linked = _link_effect_entry_buff_if_energy(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == ET_HERO:
        linked = _link_effect_hero(effect_id, params, timing, target, rate, source_name=source_name)
        if linked is not None:
            return (linked,)
    if order == ET_BUFF_BY_EQUIP_SKILL_NUM:
        linked = _link_effect_buff_by_equip_skill_num(
            effect_id, params, timing, target, rate, source_name=source_name
        )
        if linked is not None:
            return (linked,)
    if etype == 1:
        buff_ids = _buff_refs_from_params(params)
        if len(buff_ids) == 1:
            stack_count = _count_param_repeats(params, buff_ids[0])
            return _link_buff_ref(
                buff_ids[0],
                timing,
                target,
                rate,
                stack_count,
                0,
                0,
                0,
                source_name=source_name,
            )
        reason = "effect_type_1_compound" if len(buff_ids) > 1 else "effect_type_1_no_buff"
        raise _gap(
            f"effect_ref:{effect_id}",
            reason,
            source_name=source_name,
            timing=timing,
            target=target,
            rate=rate,
            effect_id=effect_id,
            effect_order=order,
            effect_type=etype,
            buff_candidates=buff_ids,
            effect_params=params,
        )
    raise _gap(
        f"effect_ref:{effect_id}",
        "effect_shape_unsupported",
        source_name=source_name,
        timing=timing,
        target=target,
        rate=rate,
        effect_id=effect_id,
        effect_order=order,
        effect_type=etype,
        effect_params=params,
    )


def _link_status_or_mark_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    stack_count: int,
) -> LinkedOp | None:
    kind = int(BUFF_KIND.get(buff_id, 0) or 0)
    if kind == 2:
        if _is_poison_status(buff_id):
            return _op("op_poison", timing, target, rate, stack_count)
        if _is_burn_status(buff_id):
            return _op("op_burn", timing, target, rate, stack_count)
        if _has_base_order(buff_id, BFT_ABSORB):
            return _op("op_leech", timing, target, rate, stack_count)
    if kind == 4:
        op_name = _mark_op_name_by_shape(buff_id)
        if op_name is not None:
            return _op(op_name, timing, target, rate, stack_count)
    return None


def _link_effect_purify(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    if (
        _param_int(params, 0) == 1
        and _param_int(params, 1) == 2
        and _param_int(params, 2) == 99
        and _param_int(params, 3) == 99
        and _param_int(params, 4) == 0
    ):
        return _op("op_dispel_debuffs", timing, target, rate)
    return None


def _link_effect_change_energy(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    direct = _param_int(params, 0)
    if direct:
        return _op("op_heal_energy", timing, target, rate, direct)
    base = _param_int(params, 1)
    ratio = _param_int(params, 2)
    if base == 0 and ratio == 0 and len(params) >= 3:
        return _op("op_heal_energy", timing, target, rate, 0)
    if base > 0 and ratio:
        amount = base * ratio // 10000
        if amount:
            return _op("op_heal_energy", timing, target, rate, amount)
    return None


def _link_effect_weather(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    pak_weather_type = _param_int(params, 0)
    kernel_weather = PAK_WEATHER_TYPE_TO_KERNEL.get(pak_weather_type)
    if kernel_weather is None:
        return None
    return _op(
        "op_weather",
        timing,
        target,
        rate,
        int(kernel_weather),
        int(PAK_WEATHER_DEFAULT_TURNS.get(pak_weather_type, 0)),
    )


def _link_effect_copy_buff(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    if (
        _param_int(params, 0) == 0
        and _param_int(params, 1) == 1
        and _param_int(params, 2) == 0
        and not _as_int_tuple(_param(params, 3))
        and _param_int(params, 4) == 99
        and _param_int(params, 5) == 1
        and _param_int(params, 6) == 1
    ):
        return _op("op_mirror_enemy_buffs", timing, target, rate)
    return None


def _mark_op_name_by_shape(buff_id: int) -> str | None:
    rows = _base_rows(buff_id)
    if _is_poison_mark(buff_id):
        return "op_poison_mark"
    if _has_order_params(rows, BFT_CHANGE_SKILL_ENERGY_COST, lambda p: _param_int(p, 3) == -1):
        return "op_moisture_mark"
    if _has_order_params(rows, BFT_NINETY_FOUR, lambda _p: True):
        return "op_meteor_mark"
    if _has_order_params(rows, BFT_ATTR_CHANGE, lambda p: _param_int(p, 0) == 6 and _param_int(p, 2) < 0):
        return "op_slow_mark"
    if _has_order_params(rows, BFT_ASSIGN, lambda p: _param_int(p, 0) == 1019001):
        return "op_solar_mark"
    if _has_order_params(rows, BFT_INC_DAM_BY_ATTACK_FIRST, lambda p: _param_int(p, 3) > 0):
        return "op_wind_mark"
    if _has_order_params(rows, BFT_NINETY_THREE, lambda p: _param_int(p, 4) == 1 and _param_int(p, 5) == 10):
        return "op_charge_mark"
    if _has_order_params(rows, BFT_SPIKES, lambda p: _param_int(p, 0) == 1019011):
        return "op_spirit_mark"
    if _has_order_params(rows, BFT_SPIKES, lambda p: _param_int(p, 0) == 1001005):
        return "op_thorn_mark"
    if _has_order_params(rows, BFT_STRENGTHEN_THE_SKILL, lambda p: _param_int(p, 0) == 6):
        return "op_dragon_mark"
    has_skill_cost_plus = _has_order_params(
        rows,
        BFT_CHANGE_SKILL_ENERGY_COST,
        lambda p: _param_int(p, 3) > 0,
    )
    has_power_plus = _has_order_params(
        rows,
        BFT_INC_DAM_BY_SKILL,
        lambda p: _param_int(p, 4) == 1 and _param_int(p, 5) > 0,
    )
    if has_skill_cost_plus and has_power_plus:
        return "op_momentum_mark"
    if has_power_plus:
        return "op_attack_mark"
    return None


def _link_active_immunity_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    if int(BUFF_KIND.get(buff_id, 0) or 0) != 3:
        return None
    if not any(BUFFBASE_ORDER.get(base_id) == BFT_IMMUNE for base_id in BUFF_BASE_IDS.get(buff_id) or ()):
        return None
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if not rules:
        return None
    if len(rules) != 1:
        return None
    reduce_type, params = rules[0]
    if int(reduce_type) != 13:
        return None
    p0 = params[0] if len(params) > 0 else 0
    p1 = params[1] if len(params) > 1 else 0
    return _op("op_apply_active_buff", timing, target, rate, buff_id, int(reduce_type), int(p0), int(p1))


def _link_zero_energy_auto_switch_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    for _base_id, order, params in _base_rows(buff_id):
        if order == BFT_IMMUNE and len(params) >= 2:
            if _single_int(params[0]) == 6 and (_single_int(params[1]) or 0) in BUFF_BASE_IDS:
                return _op("op_auto_switch_on_zero_energy", timing, target, rate)
    return None


def _link_team_skill_hit_count_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    stack_count: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != BFT_IMMUNE:
        return None
    params = rows[0][2]
    if len(params) < 2 or _as_int_tuple(params[0]) != (3,):
        return None
    skill_ids = tuple(v for v in _as_int_tuple(params[1]) if v > 0)
    if len(skill_ids) > 1:
        return None
    skill_id = skill_ids[0] if skill_ids else 0
    return _op("op_hit_count_by_team_skill_count", timing, target, rate, stack_count, skill_id)


def _link_hit_count_delta_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    stack_count: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != BFT_MULTIPLE_NUM:
        return None
    params = rows[0][2]
    if len(params) < 3:
        return None
    amount = _single_int(params[0])
    mode = _single_int(params[2])
    if amount is None or amount == 0:
        return None
    if mode == 0:
        skill_ids = tuple(v for v in _as_int_tuple(params[1]) if v > 0)
        if len(skill_ids) > 3:
            return None
        padded = (skill_ids + (0, 0, 0))[:3]
        return _op(
            "op_hit_count_delta",
            timing,
            target,
            rate,
            amount * stack_count,
            padded[0],
            padded[1],
            padded[2],
        )
    if mode == 1:
        return _op("op_hit_count_percent_delta", timing, target, rate, amount)
    return None


def _link_heal_reversal_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != BFT_O_FORTYSIX:
        return None
    params = rows[0][2]
    if len(params) < 5 or _as_int_tuple(params[0]) != (24,) or _as_int_tuple(params[4]) != (-1,):
        return None
    trigger = _as_int_tuple(params[3])
    if len(trigger) < 2:
        return None
    return _op("op_anti_heal", timing, target, rate, max(1, trigger[1] // 10))


def _link_cute_bench_cost_reduce_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    for _base_id, order, params in _base_rows(buff_id):
        if order != BFT_CHECK_BUFF_LAYER or len(params) < 3:
            continue
        condition_refs = _as_int_tuple(params[0])
        target_refs = _as_int_tuple(params[2])
        if _as_int_tuple(params[1]) != (1,) or len(target_refs) != 1:
            continue
        if not condition_refs or not _condition_refs_are_cute_effects(condition_refs):
            continue
        amount = _all_skill_cost_reduce_amount(target_refs[0])
        if amount <= 0:
            continue
        return _op("op_cute_bench_cost_reduce", timing, target, rate, amount)
    return None


def _link_conditional_hit_count_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    amount: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    base_ids = BUFF_BASE_IDS.get(buff_id) or ()
    if not base_ids or any(BUFFBASE_ORDER.get(base_id) != BFT_NINETY_ONE for base_id in base_ids):
        return None
    if amount <= 0:
        return None
    condition_refs, grant_refs = _conditional_refs_and_grants(base_ids)
    if not _grant_refs_are_hit_count_effects(grant_refs):
        return None
    if _condition_refs_are_poison_effects(condition_refs):
        return _op("op_hit_count_per_poison_effect", TIMING_HOOK_BEFORE_MOVE, target, rate, amount)
    if _condition_refs_are_cute_effects(condition_refs):
        return _op("op_cute_hit_per_stack", TIMING_HOOK_BEFORE_MOVE, target, rate, amount)
    return None


def _link_transmission_buff(
    buff_id: int,
    timing: int,
    target: int,
    rate: int,
    p0: int,
    p1: int,
    p2: int,
    p3: int,
) -> LinkedOp | None:
    base_ids = BUFF_BASE_IDS.get(buff_id) or ()
    if not base_ids or any(BUFFBASE_ORDER.get(base_id) != BFT_O_FIFTEEN for base_id in base_ids):
        return None
    if p0 > 0 and (p1 or p2 or p3):
        return _op("op_skill_mod", timing, target, rate, p0, p1, p2, p3)
    return None


def _link_effect_hit_count(
    effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    delta = _param_int(params, 0)
    per_same_skill = _param_int(params, 1)
    skill_id = _param_int(params, 2)
    if delta == -1 and per_same_skill > 0 and skill_id >= 100000:
        return _op("op_hit_count_by_team_skill_count", timing, target, rate, per_same_skill, skill_id)
    if delta > 0 and per_same_skill == 0 and skill_id == 0:
        return _op("op_hit_count_delta", timing, target, rate, delta)
    return None


def _energy_amount_from_effect_refs(
    effect_refs: tuple[int, ...],
    *,
    source_name: str,
) -> int:
    amounts: set[int] = set()
    for effect_id in effect_refs:
        if EFFECT_ORDER.get(effect_id) != ET_CHANGE_ENERGY or EFFECT_TYPE.get(effect_id) != 3:
            raise _gap(
                f"effect_ref:{effect_id}",
                "bft_o_t_non_energy_ref",
                source_name=source_name,
                timing=TIMING_PAK_SDT,
                target=0,
                rate=0,
                effect_id=effect_id,
            )
        amount = _param_int(EFFECT_PARAMS.get(effect_id) or (), 0)
        if amount <= 0:
            raise _gap(
                f"effect_ref:{effect_id}",
                "bft_o_t_non_positive_energy_ref",
                source_name=source_name,
                timing=TIMING_PAK_SDT,
                target=0,
                rate=0,
                effect_id=effect_id,
                amount=amount,
            )
        amounts.add(amount)
    if len(amounts) != 1:
        raise _gap(
            "effect_ref:*",
            "bft_o_t_mixed_energy_refs",
            source_name=source_name,
            timing=TIMING_PAK_SDT,
            target=0,
            rate=0,
            amounts=tuple(sorted(amounts)),
        )
    return amounts.pop()


def _link_effect_buff_convert(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    source_ids = _as_int_tuple(_param(params, 1))
    target_ids = _as_int_tuple(_param(params, 2))
    if _param_int(params, 0) != 0 or _param_int(params, 3) != 99 or _param_int(params, 4) != 0:
        return None
    if source_ids and _all_regular_marks(source_ids) and len(target_ids) == 1:
        if _is_internal_mark_sentinel(target_ids[0]):
            return _op("op_dispel_marks", timing, target, rate)
    if len(source_ids) == 1 and _is_internal_mark_sentinel(source_ids[0]):
        if target_ids and len(set(target_ids)) == 1 and _is_burn_status(target_ids[0]):
            return _op("op_dispel_marks_to_burn", timing, target, rate, len(target_ids))
    return None


def _link_effect_buff_by_pack_pet_num(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 3)))
    if packed == 0:
        return None
    if _param_int(params, 1) == 2:
        return _op("op_entry_self_buff_by_side_count", timing, target, rate, COUNT_FAINTED_ALLY, packed)
    element = _param_int(params, 0, -1)
    if element >= 0:
        return _op("op_entry_self_buff_by_side_count", timing, target, rate, element, packed)
    return None


def _link_effect_entry_buff_if_energy(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    selector = _param_int(params, 2)
    if selector not in (1, 2):
        return None
    packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 3)))
    if packed == 0:
        return None
    return _op("op_entry_self_buff_if_energy", timing, target, rate, selector, _param_int(params, 1), packed)


def _link_effect_hero(
    effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    if _param_int(params, 3) == 2:
        linked = _link_hero_event_count(effect_id, params, timing, target, rate)
        if linked is not None:
            return linked
    if _param_int(params, 3) != 1:
        return None
    buff_ids = _as_int_tuple(_param(params, 4))
    base_ids = _base_ids_from_buff_ids(buff_ids)
    linked = _link_entry_buff_per_used_skill_count(params, base_ids, timing, target, rate)
    if linked is not None:
        return linked
    source = _hero_count_source(params)
    if source is not None:
        linked = _link_raw_entry_element_mod_from_base_ids(
            source,
            base_ids,
            "element",
            timing,
            target,
            rate,
            source_name=source_name,
        )
        if linked is not None:
            return linked
    packed = pack_buff_delta_from_base_ids(base_ids)
    element = _param_int(params, 0, -1)
    if packed and element > 0:
        return _op("op_entry_self_buff_by_used_skill_count", timing, target, rate, element, packed)
    return None


def _link_hero_event_count(
    _effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 4)))
    if packed == 0:
        return None
    skill_dam_type = _param_int(params, 0)
    if skill_dam_type > 0:
        source = entry_source_code(ENTRY_SOURCE_ENEMY_SKILL_DAM_TYPE, skill_dam_type)
        return _op("op_entry_self_buff_by_source_count", timing, target, rate, source, packed)
    if _param_int(params, 7) == 3:
        source = entry_source_code(ENTRY_SOURCE_ENEMY_SWITCH)
        return _op("op_entry_self_buff_by_source_count", timing, target, rate, source, packed)
    return None


def _link_entry_buff_per_used_skill_count(
    params: tuple,
    base_ids: tuple[int, ...],
    timing: int,
    target: int,
    rate: int,
) -> LinkedOp | None:
    element = _param_int(params, 0, -1)
    if element <= 0 or len(base_ids) != 1:
        return None
    base_id = base_ids[0]
    order = BUFFBASE_ORDER.get(base_id)
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    if order == BFT_CHANGE_SKILL_ENERGY_COST and len(base_params) >= 4:
        cost_delta = _param_int(base_params, 3)
        if cost_delta < 0:
            return _op("op_entry_buff_per_skill_count", timing, target, rate, element, 1, abs(cost_delta))
    if order == BFT_INC_DAM_BY_SKILL and len(base_params) >= 6:
        affected = _param_int(base_params, 0)
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if affected == 0 and mode == 2 and amount > 0:
            return _op("op_entry_buff_per_skill_count", timing, target, rate, element, 2, amount)
    return None


def _hero_count_source(params: tuple) -> int | None:
    if _param_int(params, 7) == 1:
        return entry_source_code(ENTRY_SOURCE_COUNTER)
    category = _param_int(params, 2)
    if category == 2:
        return entry_source_code(ENTRY_SOURCE_STATUS)
    if category == 3:
        return entry_source_code(ENTRY_SOURCE_DEFENSE)
    element = _param_int(params, 0, -1)
    if element > 0:
        return entry_source_code(ENTRY_SOURCE_USED_ELEMENT, element)
    return None


def _link_effect_buff_by_equip_skill_num(
    effect_id: int,
    params: tuple,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    timing = TIMING_PAK_SDT
    source_skill_dam_type = _param_int(params, 0, -1)
    base_ids = _base_ids_from_buff_ids(_as_int_tuple(_param(params, 4)))
    if not base_ids:
        return None
    source_element = _skill_dam_type_to_element(source_skill_dam_type, source_name=source_name)
    source_code = entry_source_code(ENTRY_SOURCE_EQUIPPED_ELEMENT, source_element)
    linked = _link_raw_entry_element_mod_from_base_ids(
        source_code,
        base_ids,
        "skill_dam_type",
        timing,
        target,
        rate,
        source_name=source_name,
    )
    if linked is None:
        raise RuntimeError(
            f"{source_name!r} EFFECT_CONF[{effect_id}] ET_BUFF_BY_EQUIP_SKILL_NUM "
            f"has no supported BUFFBASE rows: {base_ids!r}"
        )
    return linked


def _link_raw_entry_element_mod_from_base_ids(
    source_code: int,
    base_ids: tuple[int, ...],
    mask_kind: str,
    timing: int,
    target: int,
    rate: int,
    *,
    source_name: str,
) -> LinkedOp | None:
    parsed = [
        item
        for base_id in base_ids
        for item in (_decode_entry_element_base(base_id, mask_kind, source_name=source_name),)
        if item is not None
    ]
    if not parsed:
        return None
    op_names = {op_name for _mask, _amount, op_name in parsed}
    amounts = {amount for _mask, amount, _op_name in parsed}
    if len(op_names) != 1 or len(amounts) != 1:
        raise RuntimeError(
            f"{source_name!r} raw entry element mod has mixed modes/amounts: {parsed!r}"
        )
    mask = 0
    for item_mask, _amount, _op_name in parsed:
        mask |= item_mask
    _first_mask, amount, op_name = parsed[0]
    return _op(op_name, timing, target, rate, source_code, mask, amount)


def _decode_entry_element_base(
    base_id: int,
    mask_kind: str,
    *,
    source_name: str,
) -> tuple[int, int, str] | None:
    base_params = BUFFBASE_PARAMS.get(base_id) or ()
    order = BUFFBASE_ORDER.get(base_id)
    if order == BFT_INC_DAM_BY_SKILL and len(base_params) >= 6:
        mask = _element_mask(base_params[0], mask_kind)
        mode = _param_int(base_params, 4)
        amount = _param_int(base_params, 5)
        if mask and mode == 1 and amount > 0:
            return mask, amount, "op_entry_element_power_bps_by_count"
        if mask and mode == 2 and amount > 0:
            return mask, amount, "op_entry_element_power_flat_by_count"
    elif order == BFT_CHANGE_SKILL_ENERGY_COST and len(base_params) >= 4:
        mask = _element_mask(base_params[0], mask_kind)
        cost_delta = _param_int(base_params, 3)
        if mask and cost_delta < 0:
            return mask, abs(cost_delta), "op_entry_element_cost_reduce_by_count"
    elif order == BFT_BUFF_AFTER_SKILL and len(base_params) >= 5:
        mask = _element_mask(base_params[0], mask_kind)
        if mask:
            return mask, 1, "op_entry_element_poison_stacks_by_count"
    elif order == BFT_DAMNUM_CHANGE and len(base_params) >= 5:
        mask = _element_mask(base_params[0], mask_kind)
        categories = set(_as_int_tuple(base_params[1]))
        amount = _param_int(base_params, 4)
        if mask and categories == {2, 3} and amount < 0:
            return mask, abs(amount) // 100, "op_entry_element_damage_reduce_by_count"
    elif order == BFT_NINETY_EIGHT and len(base_params) >= 2:
        mask = _element_mask(base_params[0], mask_kind)
        amount = _param_int(base_params, 1)
        if mask and amount < 0:
            return mask, 1, "op_entry_element_damage_resist_by_count"
    return None


def _element_mask(value: object, mask_kind: str) -> int:
    mask = 0
    for raw in _as_int_tuple(value):
        if mask_kind == "skill_dam_type":
            element = SKILL_DAM_TYPE_TO_ELEMENT.get(raw)
            if element is None:
                continue
        else:
            if raw <= 0:
                continue
            element = raw
        if _valid_element(element):
            mask |= 1 << int(element)
    return mask


def _skill_dam_type_to_element(skill_dam_type: int, *, source_name: str) -> int:
    element = SKILL_DAM_TYPE_TO_ELEMENT.get(skill_dam_type)
    if element is None:
        raise RuntimeError(f"{source_name!r} references unmapped SkillDamType {skill_dam_type}")
    if not _valid_element(element):
        raise RuntimeError(
            f"{source_name!r} SkillDamType {skill_dam_type} maps to invalid element {element}"
        )
    return int(element)


def _valid_element(element: object) -> bool:
    try:
        Element(int(element))
        return True
    except (TypeError, ValueError):
        return False


def _base_rows(buff_id: int) -> tuple[tuple[int, int, tuple], ...]:
    rows: list[tuple[int, int, tuple]] = []
    for base_id in BUFF_BASE_IDS.get(buff_id) or ():
        rows.append((int(base_id), int(BUFFBASE_ORDER.get(base_id, 0) or 0), BUFFBASE_PARAMS.get(base_id) or ()))
    return tuple(rows)


def _has_base_order(buff_id: int, order: int) -> bool:
    return any(row_order == order for _base_id, row_order, _params in _base_rows(buff_id))


def _has_order_params(
    rows: tuple[tuple[int, int, tuple], ...],
    order: int,
    predicate,
) -> bool:
    return any(row_order == order and predicate(params) for _base_id, row_order, params in rows)


def _is_poison_status(buff_id: int) -> bool:
    return _has_order_params(
        _base_rows(buff_id),
        BFT_DAM,
        lambda params: _param_int(params, 4) == 12,
    )


def _is_burn_status(buff_id: int) -> bool:
    return _has_order_params(
        _base_rows(buff_id),
        BFT_DAM,
        lambda params: _param_int(params, 4) == 4,
    )


def _is_poison_mark(buff_id: int) -> bool:
    return int(BUFF_KIND.get(buff_id, 0) or 0) == 4 and _is_poison_status(buff_id)


def _conditional_refs_and_grants(base_ids: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    condition_refs: list[int] = []
    grant_refs: list[int] = []
    for base_id in base_ids:
        params = BUFFBASE_PARAMS.get(base_id) or ()
        if len(params) > 1:
            condition_refs.extend(_as_int_tuple(params[1]))
        if len(params) > 3:
            grant_refs.extend(_as_int_tuple(params[3]))
    return tuple(condition_refs), tuple(grant_refs)


def _grant_refs_are_hit_count_effects(ref_ids: tuple[int, ...]) -> bool:
    if not ref_ids:
        return False
    for ref_id in ref_ids:
        base_ids = BUFF_BASE_IDS.get(ref_id)
        if not base_ids:
            return False
        if not any(BUFFBASE_ORDER.get(base_id) == BFT_O_EIGHT for base_id in base_ids):
            return False
    return True


def _condition_refs_are_poison_effects(ref_ids: tuple[int, ...]) -> bool:
    has_status = False
    has_mark = False
    for ref_id in ref_ids:
        if ref_id not in BUFF_BASE_IDS:
            return False
        if _is_poison_mark(ref_id):
            has_mark = True
        elif _is_poison_status(ref_id):
            has_status = True
        else:
            return False
    return has_status and has_mark


def _condition_refs_are_cute_effects(ref_ids: tuple[int, ...]) -> bool:
    if not ref_ids:
        return False
    for ref_id in ref_ids:
        base_ids = BUFF_BASE_IDS.get(ref_id)
        if not base_ids:
            return False
        if not all(BUFFBASE_ORDER.get(base_id) == BFT_O_TWO for base_id in base_ids):
            return False
    return True


def _all_skill_cost_reduce_amount(buff_id: int) -> int:
    rows = _base_rows(buff_id)
    if len(rows) != 1 or rows[0][1] != BFT_CHANGE_SKILL_ENERGY_COST:
        return 0
    params = rows[0][2]
    if len(params) < 4 or _as_int_tuple(params[0]) != (0,):
        return 0
    cost_delta = _single_int(params[3])
    return abs(cost_delta) if cost_delta is not None and cost_delta < 0 else 0


def _all_regular_marks(buff_ids: tuple[int, ...]) -> bool:
    return bool(buff_ids) and all(int(BUFF_KIND.get(buff_id, 0) or 0) == 4 for buff_id in buff_ids)


def _is_internal_mark_sentinel(buff_id: int) -> bool:
    if int(BUFF_KIND.get(buff_id, 0) or 0) != 3:
        return False
    rules = BUFF_REDUCE_RULES.get(buff_id) or ()
    if not any(int(rule[0]) == 13 and len(rule[1]) >= 2 and int(rule[1][1]) == 99 for rule in rules):
        return False
    return _has_base_order(buff_id, BFT_ATTR_CHANGE)


def _pack_buff_delta_from_buff_ids(buff_ids: tuple[int, ...]) -> int:
    return pack_buff_delta_from_base_ids(_base_ids_from_buff_ids(buff_ids))


def _base_ids_from_buff_ids(buff_ids: tuple[int, ...]) -> tuple[int, ...]:
    out: list[int] = []
    for buff_id in buff_ids:
        out.extend(int(v) for v in BUFF_BASE_IDS.get(buff_id) or () if v)
    return tuple(out)


def _buff_refs_from_params(params: tuple) -> tuple[int, ...]:
    seen: list[int] = []
    for value in params:
        for raw in _as_int_tuple(value):
            if raw in BUFF_BASE_IDS and raw not in seen:
                seen.append(raw)
    return tuple(seen)


def _count_param_repeats(params: tuple, ref_id: int) -> int:
    best = 1
    for value in params:
        count = _as_int_tuple(value).count(ref_id)
        if count > best:
            best = count
    return best


def _param(params: tuple, index: int) -> object:
    return params[index] if index < len(params) else 0


def _single_int(value: object) -> int | None:
    values = _as_int_tuple(value)
    return values[0] if len(values) == 1 else None


def _as_int_tuple(value: object) -> tuple[int, ...]:
    raw_values = value if isinstance(value, (list, tuple)) else (value,)
    out: list[int] = []
    for raw in raw_values:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _param_int(params_raw: tuple, index: int, default: int = 0) -> int:
    if index >= len(params_raw):
        return default
    value = params_raw[index]
    if isinstance(value, tuple):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
