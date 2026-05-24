"""Source-description decoders for pak rows whose params need text to disambiguate.

This module is deliberately narrow: it only emits when pak structure proves
the primitive family and the source skill/ability text supplies the missing
amount or slot condition. Unsupported parts stay as GapOutcome rows.
"""

from __future__ import annotations

import re
from typing import Any

from roco.compiler_v2.effect_codegen.outcomes import EmitOutcome, GapOutcome
from roco.engine.kernel.op_rows import TIMING_BEFORE_MOVE
from roco.generated import handler_indices as hi
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS

ET_INLAY = 83
BFT_CONDITIONAL_GRANT = 91
BFT_BASE_EFFECT = 108
BFT_TRANSMISSION = 115
CUTE_BUFFBASE_PREFIX = 2102

_TAG_RE = re.compile(r"</?[^>]+>")
_SLOT_CLAUSE_RE = re.compile(r"本技能位于(?P<slots>.*?)时[，,]?(?P<body>[^。；]*)")
_SLOT_RE = re.compile(r"([1-4])号(?:位)?")
_HIT_BONUS_RE = re.compile(r"连击(?:数|次数)?\+(\d+)")
_TRANSMISSION_RE = re.compile(r"传动\s*(\d*)")


def decode_source_context(
    ref_id: int,
    pak_data: Any,
    source_row: dict | None,
) -> list[tuple[EmitOutcome | GapOutcome, int | None]] | None:
    """Decode source-text dependent primitives for one effect/buff reference."""
    if not source_row:
        return None
    text = _source_text(source_row)
    if not text:
        return None

    if ref_id in pak_data.buff_conf:
        buff_rec = pak_data.buff_conf[ref_id]
        if _is_conditional_grant_buff(buff_rec):
            hit_outcome = _decode_conditional_hit_count(buff_rec, pak_data.buff_conf, text)
            if hit_outcome is not None:
                return [(hit_outcome, TIMING_BEFORE_MOVE)]
        if _is_transmission_buff(buff_rec):
            outcomes = _decode_slot_skill_mod(text)
            _append_transmission_gap(
                outcomes,
                ref_id=ref_id,
                effect_id=None,
                buff_id=ref_id,
                text=text,
                source_row=source_row,
            )
            return outcomes or None

    effect_rec = pak_data.effect_conf.get(ref_id)
    if effect_rec is None:
        return None
    if int(effect_rec.get("effect_order", 0) or 0) == ET_INLAY:
        outcomes = _decode_slot_skill_mod(text)
        if _transmission_amount(text) is not None:
            _append_transmission_gap(
                outcomes,
                ref_id=ref_id,
                effect_id=ref_id,
                buff_id=None,
                text=text,
                source_row=source_row,
            )
        return outcomes or None
    return None


def _source_text(source_row: dict) -> str:
    fields = (
        source_row.get("name"),
        source_row.get("desc"),
        source_row.get("effect_text"),
        source_row.get("description"),
        source_row.get("flavor_text"),
        (source_row.get("_move_record") or {}).get("description"),
    )
    parts = [_clean_text(value) for value in fields]
    return " ".join(part for part in parts if part)


def _clean_text(value: object) -> str:
    text = str(value or "").replace("\u200b", "")
    text = _TAG_RE.sub("", text)
    return text.strip()


def _as_int_tuple(value: object) -> tuple[int, ...]:
    if isinstance(value, tuple):
        values = value
    elif isinstance(value, list):
        values = tuple(value)
    elif value is None:
        values = ()
    else:
        values = (value,)
    out: list[int] = []
    for raw in values:
        try:
            item = int(raw)
        except (TypeError, ValueError):
            continue
        if item:
            out.append(item)
    return tuple(out)


def _is_conditional_grant_buff(buff_rec: dict) -> bool:
    base_ids = [int(v) for v in buff_rec.get("buff_base_ids") or () if v]
    return bool(base_ids) and all(
        BUFFBASE_ORDER.get(base_id) == BFT_CONDITIONAL_GRANT
        for base_id in base_ids
    )


def _conditional_refs_and_grants(buff_rec: dict) -> tuple[tuple[int, ...], tuple[int, ...]]:
    condition_refs: list[int] = []
    grant_refs: list[int] = []
    for base_id in (int(v) for v in buff_rec.get("buff_base_ids") or () if v):
        params = BUFFBASE_PARAMS.get(base_id) or ()
        if len(params) > 1:
            condition_refs.extend(_as_int_tuple(params[1]))
        if len(params) > 3:
            grant_refs.extend(_as_int_tuple(params[3]))
    return tuple(condition_refs), tuple(grant_refs)


def _decode_conditional_hit_count(
    buff_rec: dict,
    buff_conf: dict[int, dict],
    text: str,
) -> EmitOutcome | None:
    amount = _hit_count_bonus(text)
    if amount is None:
        return None
    condition_refs, grant_refs = _conditional_refs_and_grants(buff_rec)
    if not _grant_refs_are_hit_count_effects(grant_refs, buff_conf):
        return None

    if "中毒效果" in text and _condition_refs_are_poison_effects(condition_refs, buff_conf):
        handler = getattr(hi, "H_HIT_COUNT_PER_POISON_EFFECT", 0)
        if handler > 0:
            return EmitOutcome(handler, amount, 0, 0, 0, 1)
        return None
    if "萌化" in text and _condition_refs_are_cute_effects(condition_refs, buff_conf):
        return EmitOutcome(hi.H_CUTE_HIT_PER_STACK, amount, 0, 0, 0, 1)
    return None


def _hit_count_bonus(text: str) -> int | None:
    match = _HIT_BONUS_RE.search(text)
    return int(match.group(1)) if match else None


def _grant_refs_are_hit_count_effects(
    grant_refs: tuple[int, ...],
    buff_conf: dict[int, dict],
) -> bool:
    if not grant_refs:
        return False
    for ref_id in grant_refs:
        rec = buff_conf.get(ref_id)
        if rec is None:
            return False
        base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
        if not any(BUFFBASE_ORDER.get(base_id) == BFT_BASE_EFFECT for base_id in base_ids):
            return False
    return True


def _condition_refs_are_poison_effects(
    condition_refs: tuple[int, ...],
    buff_conf: dict[int, dict],
) -> bool:
    has_status = False
    has_mark = False
    for ref_id in condition_refs:
        rec = buff_conf.get(ref_id)
        if rec is None:
            return False
        label = _record_text(rec)
        if "中毒" not in label:
            return False
        if "印记" in label or int(rec.get("type", 0) or 0) == 4:
            has_mark = True
        else:
            has_status = True
    return has_status and has_mark


def _condition_refs_are_cute_effects(
    condition_refs: tuple[int, ...],
    buff_conf: dict[int, dict],
) -> bool:
    if not condition_refs:
        return False
    for ref_id in condition_refs:
        rec = buff_conf.get(ref_id)
        if rec is None:
            return False
        base_ids = [int(v) for v in rec.get("buff_base_ids") or () if v]
        if not base_ids or not all(base_id // 1000 == CUTE_BUFFBASE_PREFIX for base_id in base_ids):
            return False
    return True


def _record_text(rec: dict) -> str:
    fields = (rec.get("name"), rec.get("add_des"), rec.get("desc"), rec.get("editor_name"))
    return " ".join(_clean_text(value) for value in fields if value)


def _is_transmission_buff(buff_rec: dict) -> bool:
    base_ids = [int(v) for v in buff_rec.get("buff_base_ids") or () if v]
    return bool(base_ids) and all(
        BUFFBASE_ORDER.get(base_id) == BFT_TRANSMISSION
        for base_id in base_ids
    )


def _decode_slot_skill_mod(text: str) -> list[tuple[EmitOutcome | GapOutcome, int | None]]:
    for match in _SLOT_CLAUSE_RE.finditer(text):
        mask = _slot_mask(match.group("slots"))
        if mask == 0:
            continue
        body = match.group("body")
        cost_reduce = _first_int(r"能耗-(\d+)", body)
        power_bonus = _first_int(r"威力\+(\d+)", body)
        hit_bonus = _first_int(r"连击(?:数|次数)?\+(\d+)", body)
        if cost_reduce is None and power_bonus is None and hit_bonus is None:
            continue
        return [(
            EmitOutcome(
                hi.H_SKILL_MOD,
                mask,
                cost_reduce or 0,
                power_bonus or 0,
                hit_bonus or 0,
                1,
            ),
            TIMING_BEFORE_MOVE,
        )]
    return []


def _slot_mask(text: str) -> int:
    mask = 0
    for match in _SLOT_RE.finditer(text):
        slot = int(match.group(1)) - 1
        mask |= 1 << slot
    return mask


def _first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def _append_transmission_gap(
    outcomes: list[tuple[EmitOutcome | GapOutcome, int | None]],
    *,
    ref_id: int,
    effect_id: int | None,
    buff_id: int | None,
    text: str,
    source_row: dict,
) -> None:
    amount = _transmission_amount(text) or 1
    outcomes.append((
        GapOutcome(
            primitive="transmission",
            effect_id=effect_id,
            buff_id=buff_id,
            reason="transmission_unimplemented",
            params={
                "effect_id": effect_id,
                "buff_id": buff_id,
                "ref_id": ref_id,
                "amount": amount,
                "source_id": source_row.get("id") or source_row.get("feature_id"),
            },
        ),
        None,
    ))


def _transmission_amount(text: str) -> int | None:
    match = _TRANSMISSION_RE.search(text)
    if not match:
        return None
    raw = match.group(1)
    return int(raw) if raw else 1
