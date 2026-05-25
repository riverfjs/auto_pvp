"""Engine linker for exact pak ``BUFF_CONF`` / ``EFFECT_CONF`` references."""
from __future__ import annotations
from roco.common.primitive_keys import BUFF_REF_PREFIX, EFFECT_REF_PREFIX, strip_prefix
from roco.engine.artifacts.linked_op import LinkedOp
from roco.engine.artifacts.pak_ref_buffs import link_buff_ref as _link_buff_ref_impl
from roco.engine.artifacts.pak_ref_common import BUFF_BASE_IDS, EFFECT_ORDER, _element_mask, _gap
from roco.engine.artifacts.pak_ref_effects import link_effect_ref as _link_effect_ref_impl

def link_pak_ref(primitive: str, timing: int, target: int, rate: int, p0: int, p1: int, p2: int, p3: int, *, source_name: str) -> tuple[LinkedOp, ...] | None:
    buff_ref = strip_prefix(primitive, BUFF_REF_PREFIX)
    if buff_ref is not None:
        try:
            return _link_buff_ref(int(buff_ref), timing, target, rate, p0, p1, p2, p3, source_name=source_name)
        except ValueError as exc:
            raise RuntimeError(f'{source_name!r} produced malformed buff ref {primitive!r}') from exc
    effect_ref = strip_prefix(primitive, EFFECT_REF_PREFIX)
    if effect_ref is not None:
        try:
            return _link_effect_ref(int(effect_ref), timing, target, rate, p0, p1, p2, p3, source_name=source_name)
        except ValueError as exc:
            raise RuntimeError(f'{source_name!r} produced malformed effect ref {primitive!r}') from exc
    return None

def _link_ref_id(ref_id: int, timing: int, target: int, rate: int, *, source_name: str) -> tuple[LinkedOp, ...]:
    if ref_id in EFFECT_ORDER:
        return _link_effect_ref(ref_id, timing, target, rate, 0, 0, 0, 0, source_name=source_name)
    if ref_id in BUFF_BASE_IDS:
        return _link_buff_ref(ref_id, timing, target, rate, 0, 0, 0, 0, source_name=source_name)
    raise _gap(f'pak_ref:{ref_id}', 'assigned_ref_not_in_pak', source_name=source_name, timing=timing, target=target, rate=rate, ref_id=ref_id)

def _link_buff_ref(buff_id: int, timing: int, target: int, rate: int, p0: int, p1: int, p2: int, p3: int, *, source_name: str) -> tuple[LinkedOp, ...]:
    return _link_buff_ref_impl(buff_id, timing, target, rate, p0, p1, p2, p3, source_name=source_name, link_ref_id=_link_ref_id)

def _link_effect_ref(effect_id: int, timing: int, target: int, rate: int, p0: int, p1: int, p2: int, p3: int, *, source_name: str) -> tuple[LinkedOp, ...]:
    return _link_effect_ref_impl(effect_id, timing, target, rate, p0, p1, p2, p3, source_name=source_name, link_buff_ref=_link_buff_ref)
