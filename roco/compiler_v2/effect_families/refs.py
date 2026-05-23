"""Cross-reference + desc-note collection for the family catalog.

* :func:`_cross_refs` cites the specific EFFECT_CONF / BUFF_CONF / SKILL_CONF
  ids each family's params point at, alongside the referenced ``editor_name``
  for human review.
* :func:`_desc_note_refs` extracts ``<desc_id=N>`` tags from editor_name /
  add_des / referenced buff descriptions and resolves them against
  DESC_NOTE_CONF.

:func:`_sample_sorted` is a deterministic-order sampling helper used by
both ``_cross_refs`` and the family driver (``_build_family``) for sample
consumers.  It lives here because ``_cross_refs`` is its primary consumer.
"""

from __future__ import annotations

import json
import re
from typing import Any

from roco.compiler_v2.effect_codegen.pak import PakTables

from .params import _vec_from_param_slot


DESC_ID_RE = re.compile(r"<desc_id=(\d+)>")


def _sample_sorted(values: list[Any], limit: int = 5) -> list[Any]:
    """Stable sample for catalog output: dedupe + sort + take first ``limit``."""
    seen: list[Any] = []
    seen_keys: set[str] = set()
    for v in values:
        key = json.dumps(v, ensure_ascii=False, sort_keys=True)
        if key not in seen_keys:
            seen_keys.add(key)
            seen.append(v)
    seen.sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
    return seen[:limit]


def _cross_refs(
    source_ids: list[int],
    record_lookup: dict[int, dict],
    pak: PakTables,
) -> dict:
    """Concrete cross-reference samples (effect_refs / buff_refs / skill_refs).

    Distinct from ``param_shape.slots[].*_count`` which only counts;
    here we cite *specific* referenced ids + their pak ``editor_name``.
    """
    effect_refs: dict[int, dict] = {}
    buff_refs: dict[int, dict] = {}
    skill_refs: dict[int, dict] = {}
    base_id_prefixes: set[int] = set()
    for sid in source_ids:
        rec = record_lookup.get(sid)
        if rec is None:
            continue
        params = rec.get("effect_param") or rec.get("params") or []
        for slot in params:
            for v in _vec_from_param_slot(slot):
                if v <= 0:
                    continue
                if v in pak.effect_conf and v not in source_ids:
                    other = pak.effect_conf[v]
                    effect_refs.setdefault(v, {
                        "effect_id": v,
                        "editor_name": str(other.get("editor_name", "")),
                    })
                if v in pak.buff_conf:
                    other = pak.buff_conf[v]
                    base_ids = [int(b) for b in (other.get("buff_base_ids") or []) if b]
                    if base_ids:
                        base_id_prefixes.add(base_ids[0] // 1000)
                    buff_refs.setdefault(v, {
                        "buff_id": v,
                        "editor_name": str(other.get("editor_name", "")),
                        "buff_base_id_prefix": (base_ids[0] // 1000) if base_ids else None,
                    })
                if v in pak.skill_conf:
                    other = pak.skill_conf[v]
                    skill_refs.setdefault(v, {
                        "skill_id": v,
                        "name": str(other.get("name", "")),
                    })
    return {
        "effect_refs_sample": _sample_sorted(list(effect_refs.values())),
        "buff_refs_sample": _sample_sorted(list(buff_refs.values())),
        "skill_refs_sample": _sample_sorted(list(skill_refs.values())),
        "buff_base_id_prefixes_seen": sorted(base_id_prefixes),
    }


def _desc_note_refs(
    source_ids: list[int],
    record_lookup: dict[int, dict],
    buff_conf: dict[int, dict],
    desc_notes: dict[int, str],
) -> list[dict]:
    """Find ``<desc_id=N>`` tags in editor_name and related buff descriptions."""
    found: dict[int, dict] = {}
    seen_text: set[str] = set()
    for sid in source_ids:
        rec = record_lookup.get(sid)
        if rec is None:
            continue
        for haystack in (rec.get("editor_name", ""), rec.get("add_des", "")):
            for m in DESC_ID_RE.finditer(str(haystack)):
                did = int(m.group(1))
                if did in desc_notes and did not in found:
                    found[did] = {"desc_id": did, "note": desc_notes[did]}
        # Pak effect_param may name buff_ids whose desc contains tags too.
        for slot in rec.get("effect_param") or []:
            for v in _vec_from_param_slot(slot):
                buff = buff_conf.get(v)
                if buff is None:
                    continue
                text = str(buff.get("desc", ""))
                if text in seen_text:
                    continue
                seen_text.add(text)
                for m in DESC_ID_RE.finditer(text):
                    did = int(m.group(1))
                    if did in desc_notes and did not in found:
                        found[did] = {"desc_id": did, "note": desc_notes[did]}
    return sorted(found.values(), key=lambda d: d["desc_id"])
