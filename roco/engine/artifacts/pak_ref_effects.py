"""EFFECT_CONF pak ref dispatcher and direct effect matchers."""
from __future__ import annotations
from roco.engine.artifacts.linked_op import (
    ACTION_KIND_EXTRA_SKILL,
    ACTION_KIND_OP_LIST,
    ACTION_KIND_RANDOM,
    EXTRA_SKILL_POLICY_CONSERVATIVE,
    LinkInertError,
    LinkedAction,
    LinkedOp,
)
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, EFFECT_ORDER, EFFECT_PARAMS, EFFECT_TYPE, _as_int_tuple, _buff_refs_from_params, _count_param_repeats, _gap, _op, _pack_buff_delta_from_buff_ids, _param, _param_int, effect_type
from roco.engine.artifacts.pak_ref_effect_entry import _link_effect_buff_by_equip_skill_num, _link_effect_buff_by_pack_pet_num, _link_effect_buff_convert, _link_effect_entry_buff_if_energy, _link_effect_hero
from roco.engine.kernel.op_rows import TIMING_PAK_BEFORE_HURT, TIMING_PAK_SDT
from roco.generated.weather_table import PAK_WEATHER_DEFAULT_TURNS, PAK_WEATHER_TYPE_TO_KERNEL

LinkedEffect = LinkedOp | LinkedAction

_ET_RANDOM_ALLOWED_SHAPES = frozenset((
    (1, 0),
    (1, 1),
    (1, 2),
    (1, 299901),
    (2, 1),
    (2, 4),
    (5, 4),
    (10, 4),
    (16, 0),
))


def link_effect_ref(effect_id: int, timing: int, target: int, rate: int, p0: int, p1: int, p2: int, p3: int, *, source_name: str, link_buff_ref) -> tuple[LinkedEffect, ...]:
    order = EFFECT_ORDER.get(effect_id)
    if order is None:
        raise _gap(f'effect_ref:{effect_id}', 'effect_id_not_in_pak', source_name=source_name, timing=timing, target=target, rate=rate, effect_id=effect_id)
    params = EFFECT_PARAMS.get(effect_id) or ()
    etype = EFFECT_TYPE.get(effect_id)
    if etype == 2:
        return (_op('op_damage', timing, target, rate, _param_int(params, 2), 0, _param_int(params, 6)),)
    if order == effect_type('ET_INLAY') and p0 > 0 and (p1 or p2 or p3):
        return (_op('op_skill_mod', timing, target, rate, p0, p1, p2, p3),)
    if order == effect_type('ET_PURIFY'):
        linked = _link_effect_purify(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_RECOVER'):
        amount = _param_int(params, 1)
        if amount:
            return (_op('op_heal_hp', timing, target, rate, amount),)
    if order == effect_type('ET_SUCKBLOOD'):
        amount = _param_int(params, 0)
        if amount:
            return (_op('op_life_drain', timing, target, rate, amount),)
    if order == effect_type('ET_CHANGE_ENERGY'):
        linked = _link_effect_change_energy(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_CHANGE_WEATHER'):
        linked = _link_effect_weather(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_COUNTER'):
        response_skill_id = _param_int(params, 0)
        if 7000000 <= response_skill_id < 8000000:
            return (_op('op_install_counter', TIMING_PAK_BEFORE_HURT, target, rate, response_skill_id),)
    if order == effect_type('ET_MULTIPLE'):
        linked = _link_effect_hit_count(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_SERIES_SKILL'):
        linked_action = _link_effect_series_skill(effect_id, params, timing, target, rate)
        if linked_action is not None:
            return (linked_action,)
    if order == effect_type('ET_RANDOM'):
        linked_action = _link_effect_random(
            effect_id,
            params,
            timing,
            target,
            rate,
            source_name=source_name,
            link_buff_ref=link_buff_ref,
        )
        if linked_action is not None:
            return (linked_action,)
    if order == effect_type('ET_SKILL_CD'):
        turns = _param_int(params, 0)
        if turns > 0 and _param_int(params, 2) == 1 and (_param_int(params, 3) == 0):
            return (_op('op_set_self_cooldown', timing, target, rate, turns),)
    if order == effect_type('ET_FAST_SKILL'):
        delta = _param_int(params, 2)
        if delta:
            return (_op('op_priority_next_delta', timing, target, rate, delta),)
    if order == effect_type('ET_SWAP_STAT'):
        mode = _param_int(params, 0)
        if mode == 1:
            return (_op('op_exchange_hp_ratio', timing, target, rate),)
        if mode == 3:
            return (_op('op_transfer_mods', timing, target, rate),)
    if order == effect_type('ET_SWAP_SKILLS') and _param_int(params, 0) == 1:
        return (_op('op_exchange_moves', timing, target, rate),)
    if order == effect_type('ET_COPY_BUFF'):
        linked = _link_effect_copy_buff(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_BUFF_CONVERT'):
        linked = _link_effect_buff_convert(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_BUFF_BY_PACK_PET_NUM'):
        linked = _link_effect_buff_by_pack_pet_num(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_BUFF_BY_CHANGE_TIMES'):
        packed = _pack_buff_delta_from_buff_ids(_as_int_tuple(_param(params, 0)))
        if packed:
            return (_op('op_self_buff', TIMING_PAK_SDT, target, rate, packed),)
    if order == effect_type('ET_LIMIT_FIGHT_BY_HP'):
        linked = _link_effect_entry_buff_if_energy(effect_id, params, timing, target, rate)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_HERO'):
        linked = _link_effect_hero(effect_id, params, timing, target, rate, source_name=source_name)
        if linked is not None:
            return (linked,)
    if order == effect_type('ET_BUFF_BY_EQUIP_SKILL_NUM'):
        linked = _link_effect_buff_by_equip_skill_num(effect_id, params, timing, target, rate, source_name=source_name)
        if linked is not None:
            return (linked,)
    if etype == 1:
        buff_ids = _buff_refs_from_params(params)
        if len(buff_ids) == 1:
            stack_count = _count_param_repeats(params, buff_ids[0])
            return link_buff_ref(buff_ids[0], timing, target, rate, stack_count, 0, 0, 0, source_name=source_name)
        if len(buff_ids) > 1:
            ops: list[LinkedOp] = []
            for buff_id in buff_ids:
                stack_count = _count_param_repeats(params, buff_id)
                try:
                    linked = link_buff_ref(buff_id, timing, target, rate, stack_count, 0, 0, 0, source_name=source_name)
                except LinkInertError:
                    continue
                if not all(isinstance(item, LinkedOp) for item in linked):
                    break
                ops.extend(linked)
            else:
                if ops:
                    return (
                        LinkedAction(
                            ACTION_KIND_OP_LIST,
                            timing,
                            target,
                            rate,
                            tuple(ops),
                            source_ref=effect_id,
                        ),
                    )
        reason = 'effect_type_1_compound' if len(buff_ids) > 1 else 'effect_type_1_no_buff'
        raise _gap(f'effect_ref:{effect_id}', reason, source_name=source_name, timing=timing, target=target, rate=rate, effect_id=effect_id, effect_order=order, effect_type=etype, buff_candidates=buff_ids, effect_params=params)
    raise _gap(f'effect_ref:{effect_id}', 'effect_shape_unsupported', source_name=source_name, timing=timing, target=target, rate=rate, effect_id=effect_id, effect_order=order, effect_type=etype, effect_params=params)


def _link_effect_series_skill(effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedAction | None:
    if len(params) < 2:
        return None
    mode = _param_int(params, 0)
    skill_id = _param_int(params, 1)
    if mode == 0 and skill_id > 0 and not any(_param_int(params, idx) for idx in range(2, len(params))):
        return LinkedAction(
            ACTION_KIND_EXTRA_SKILL,
            timing,
            target,
            rate,
            (skill_id, EXTRA_SKILL_POLICY_CONSERVATIVE),
            source_ref=effect_id,
        )
    return None


def _link_effect_random(effect_id: int, params: tuple, timing: int, target: int, rate: int, *, source_name: str, link_buff_ref) -> LinkedAction | None:
    if len(params) < 10:
        return None
    count = _param_int(params, 0)
    scope = _param_int(params, 9)
    if (count, scope) not in _ET_RANDOM_ALLOWED_SHAPES:
        return None
    refs = tuple(ref_id for ref_id in (_param_int(params, idx) for idx in range(1, 9)) if ref_id > 0)
    if not refs:
        return None
    choices: list[tuple[int, LinkedAction]] = []
    for ref_id in refs:
        choices.append((
            1,
            _child_ref_action(ref_id, timing, target, rate, source_name=source_name, link_buff_ref=link_buff_ref),
        ))
    return LinkedAction(
        ACTION_KIND_RANDOM,
        timing,
        target,
        rate,
        (count, tuple(choices)),
        source_ref=effect_id,
    )


def _child_ref_action(ref_id: int, timing: int, target: int, rate: int, *, source_name: str, link_buff_ref) -> LinkedAction:
    if ref_id in EFFECT_ORDER:
        linked = link_effect_ref(ref_id, timing, target, rate, 0, 0, 0, 0, source_name=source_name, link_buff_ref=link_buff_ref)
    elif ref_id in BUFF_BASE_IDS:
        try:
            linked = link_buff_ref(ref_id, timing, target, rate, 0, 0, 0, 0, source_name=source_name)
        except LinkInertError:
            return LinkedAction(ACTION_KIND_OP_LIST, timing, target, rate, (), source_ref=ref_id)
    else:
        raise _gap(f"effect_ref:{ref_id}", "child_ref_not_in_pak", source_name=source_name, timing=timing, target=target, rate=rate, effect_id=ref_id)
    if len(linked) == 1 and isinstance(linked[0], LinkedAction):
        return linked[0]
    ops = tuple(item for item in linked if isinstance(item, LinkedOp))
    if len(ops) != len(linked) or not ops:
        raise _gap(f"effect_ref:{ref_id}", "child_ref_action_unsupported", source_name=source_name, timing=timing, target=target, rate=rate, effect_id=ref_id)
    return LinkedAction(ACTION_KIND_OP_LIST, timing, target, rate, ops, source_ref=ref_id)

def _link_effect_purify(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    if _param_int(params, 0) == 1 and _param_int(params, 1) == 2 and (_param_int(params, 2) == 99) and (_param_int(params, 3) == 99) and (_param_int(params, 4) == 0):
        return _op('op_dispel_debuffs', timing, target, rate)
    return None

def _link_effect_change_energy(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    direct = _param_int(params, 0)
    if direct:
        return _op('op_heal_energy', timing, target, rate, direct)
    base = _param_int(params, 1)
    ratio = _param_int(params, 2)
    if base == 0 and ratio == 0 and (len(params) >= 3):
        return _op('op_heal_energy', timing, target, rate, 0)
    if base > 0 and ratio:
        amount = base * ratio // 10000
        if amount:
            return _op('op_heal_energy', timing, target, rate, amount)
    return None

def _link_effect_weather(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    pak_weather_type = _param_int(params, 0)
    kernel_weather = PAK_WEATHER_TYPE_TO_KERNEL.get(pak_weather_type)
    if kernel_weather is None:
        return None
    return _op('op_weather', timing, target, rate, int(kernel_weather), int(PAK_WEATHER_DEFAULT_TURNS.get(pak_weather_type, 0)))

def _link_effect_copy_buff(_effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    if _param_int(params, 0) == 0 and _param_int(params, 1) == 1 and (_param_int(params, 2) == 0) and (not _as_int_tuple(_param(params, 3))) and (_param_int(params, 4) == 99) and (_param_int(params, 5) == 1) and (_param_int(params, 6) == 1):
        return _op('op_mirror_enemy_buffs', timing, target, rate)
    return None

def _link_effect_hit_count(effect_id: int, params: tuple, timing: int, target: int, rate: int) -> LinkedOp | None:
    delta = _param_int(params, 0)
    per_same_skill = _param_int(params, 1)
    skill_id = _param_int(params, 2)
    if delta == -1 and per_same_skill > 0 and (skill_id >= 100000):
        return _op('op_hit_count_by_team_skill_count', timing, target, rate, per_same_skill, skill_id)
    if delta > 0 and per_same_skill == 0 and (skill_id == 0):
        return _op('op_hit_count_delta', timing, target, rate, delta)
    return None
