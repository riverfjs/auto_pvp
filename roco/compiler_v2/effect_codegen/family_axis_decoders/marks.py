"""Mark transform pak effect-order decoders."""

from __future__ import annotations

from functools import lru_cache

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome
from roco.compiler_v2.effect_codegen.params import extract_int_list, safe_int
from roco.compiler_v2.sources import PakSource

from roco.compiler_v2.effect_codegen.family_axis_decoders.common import (
    emit_effect_ref,
    params,
)


def decode_buff_convert(rec: dict, buff_conf: dict[int, dict]) -> EmitOutcome | None:
    params_raw = params(rec)
    source_ids = extract_int_list(params_raw, 1)
    target_ids = extract_int_list(params_raw, 2)
    if safe_int(params_raw, 0) != 0 or safe_int(params_raw, 3) != 99 or safe_int(params_raw, 4) != 0:
        return None

    if (
        source_ids
        and _all_regular_marks(source_ids, buff_conf)
        and len(target_ids) == 1
        and _is_internal_mark_sentinel(target_ids[0], buff_conf)
    ):
        return emit_effect_ref(int(rec["id"]), 0)

    if (
        len(source_ids) == 1
        and _is_internal_mark_sentinel(source_ids[0], buff_conf)
        and target_ids
        and len(set(target_ids)) == 1
        and _is_burn_family(target_ids[0], buff_conf)
    ):
        return emit_effect_ref(int(rec["id"]), 0)
    return None


def _all_regular_marks(buff_ids: list[int], buff_conf: dict[int, dict]) -> bool:
    for buff_id in buff_ids:
        rec = buff_conf.get(buff_id)
        if rec is None or int(rec.get("type", 0) or 0) != 4:
            return False
    return True


def _is_internal_mark_sentinel(buff_id: int, buff_conf: dict[int, dict]) -> bool:
    rec = buff_conf.get(buff_id)
    if rec is None:
        return False
    name = str(rec.get("editor_name") or rec.get("name") or "")
    if "标记" in name and _is_self_buff_family(buff_id, buff_conf):
        return True
    if name:
        return False
    if int(rec.get("type", 0) or 0) != 3 or int(rec.get("add_max", 0) or 0) != 99:
        return False
    if not _is_self_buff_family(buff_id, buff_conf):
        return False
    for reduce_rule in rec.get("buff_group_reduce") or []:
        if not isinstance(reduce_rule, dict):
            continue
        if int(reduce_rule.get("reduce_type") or 0) != 13:
            continue
        params_raw = reduce_rule.get("reduce_param") or []
        if len(params_raw) >= 2 and int(params_raw[1] or 0) == 99:
            return True
    return False


def _is_burn_family(buff_id: int, buff_conf: dict[int, dict]) -> bool:
    rec = buff_conf.get(buff_id)
    if rec is None:
        return False
    for base_id in rec.get("buff_base_ids") or []:
        if _buffbase_order(int(base_id)) == 7:
            return True
    return False


def _is_self_buff_family(buff_id: int, buff_conf: dict[int, dict]) -> bool:
    rec = buff_conf.get(buff_id)
    if rec is None:
        return False
    for base_id in rec.get("buff_base_ids") or []:
        if _buffbase_order(int(base_id)) == 1:
            return True
    return False


def _buffbase_order(base_id: int) -> int:
    return _buffbase_orders().get(base_id, 0)


@lru_cache(maxsize=1)
def _buffbase_orders() -> dict[int, int]:
    rows = PakSource().table("BUFFBASE_CONF")
    out: dict[int, int] = {}
    for raw_id, rec in rows.items():
        if not isinstance(raw_id, int):
            continue
        try:
            out[raw_id] = int(rec.get("buffbase_order") or 0)
        except (TypeError, ValueError):
            continue
    return out
