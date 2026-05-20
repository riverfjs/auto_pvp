"""Per-family record assembly + the ``build_families()`` driver.

``_build_family`` constructs one catalog dict from a list of source ids.
``build_families`` is the top-level orchestrator: load pak + canonical,
build consumer / team indices, run the ability-flag cross-check, then
emit one record per EFFECT_CONF (type, effect_order) bucket and one per
BUFF_CONF_DIRECT prefix bucket.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from roco.compiler.effect_codegen.ability_flags_from_effects import (
    load_ability_flags_from_effects,
)
from roco.compiler.effect_codegen.pak import PakTables
from roco.generated.weather_decoders import WEATHER_EFFECT_DECODERS

from .classify import (
    _buff_family_key,
    _classify_one_source_id,
    _derive_coverage_status,
)
from .consumers import _build_consumer_index, _build_team_used
from .io import _load_canonical, _load_desc_notes, _load_exact_rules
from .paths import PAK_DATA
from .validation import _validate_ability_flag_rules


# Editor-name keywords that mark a pak effect as visual-only candidate.
# Only flags — Phase 1 does NOT promote these to ignored rules.
VISUAL_KEYWORDS = ("动效", "飘字", "动画", "特效")

DESC_ID_RE = re.compile(r"<desc_id=(\d+)>")


def _vec_from_param_slot(slot: Any) -> tuple[int, ...]:
    """pak slot → integer tuple.  Empty / non-list → ``()``."""
    if isinstance(slot, dict):
        inner = slot.get("params")
        if isinstance(inner, list):
            return tuple(int(x) for x in inner if isinstance(x, (int, float)))
    if isinstance(slot, list):
        return tuple(int(x) for x in slot if isinstance(x, (int, float)))
    if isinstance(slot, (int, float)):
        return (int(slot),)
    return ()


def _classify_slot_refs(
    vectors: list[tuple[int, ...]],
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    skill_conf: dict[int, dict],
) -> dict[str, int]:
    """Per-slot count of how many values reference EFFECT/BUFF/SKILL ids."""
    counts = {
        "effect_ref_count": 0,
        "buff_ref_count": 0,
        "skill_ref_count": 0,
        "non_ref_count": 0,
    }
    for vec in vectors:
        for v in vec:
            if v <= 0:
                counts["non_ref_count"] += 1
            elif v in effect_conf:
                counts["effect_ref_count"] += 1
            elif v in buff_conf:
                counts["buff_ref_count"] += 1
            elif v in skill_conf:
                counts["skill_ref_count"] += 1
            else:
                counts["non_ref_count"] += 1
    return counts


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


def _has_visual_keyword(text: str) -> str | None:
    for kw in VISUAL_KEYWORDS:
        if kw in text:
            return kw
    return None


def _collect_param_shape(
    source_ids: list[int],
    record_lookup: dict[int, dict],
    pak: PakTables,
) -> dict:
    """Build the ``param_shape`` sub-document from a family's source rows.

    For each slot index seen across the family's effect_param rows, collect:
    distinct vectors (up to 10), distinct count, sample vectors, and per-slot
    cross-reference counts (effect / buff / skill / non_ref).
    """
    observed_lengths: set[int] = set()
    by_slot: dict[int, list[tuple[int, ...]]] = defaultdict(list)
    for sid in source_ids:
        rec = record_lookup.get(sid)
        if rec is None:
            continue
        params = rec.get("effect_param") or rec.get("params") or []
        observed_lengths.add(len(params))
        for idx, slot in enumerate(params):
            by_slot[idx].append(_vec_from_param_slot(slot))
    slots: list[dict] = []
    for idx in sorted(by_slot):
        vecs = by_slot[idx]
        unique: list[tuple[int, ...]] = []
        for v in vecs:
            if v not in unique:
                unique.append(v)
        unique.sort()
        distinct = len(unique)
        if distinct <= 10:
            observed_vectors = [list(v) for v in unique]
            sample_vectors = observed_vectors
        else:
            observed_vectors = []
            sample_vectors = [list(v) for v in unique[:5]]
        refs = _classify_slot_refs(vecs, pak.effect_conf, pak.buff_conf, pak.skill_conf)
        slots.append({
            "slot": idx,
            "observed_param_vectors": observed_vectors,
            "distinct_vector_count": distinct,
            "sample_vectors": sample_vectors,
            **refs,
        })
    return {
        "observed_lengths": sorted(observed_lengths),
        "slots": slots,
    }


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


def _ignored_candidate(
    source_ids: list[int],
    record_lookup: dict[int, dict],
) -> tuple[bool, str, list[dict]]:
    """Determine ignored-candidate status at family granularity.

    Returns ``(family_level_flag, reason, per_source_hits)``.

    * ``family_level_flag`` is ``True`` only when **every** source_id in
      the family has a visual-only keyword in its ``editor_name``.  This
      avoids the prior false-positive where a single ``月牙雪熊飘字用``
      row marked the whole ``buff_conf_direct:prefix_2040`` family
      (which also contains 天光 / 月光合奏 / 击鼓传花 real blockers).
    * ``per_source_hits`` lists every individual source_id whose
      editor_name matched a visual keyword — those are real
      ignored-rule candidates that future audit work should review.
    """
    hits: list[dict] = []
    for sid in source_ids:
        rec = record_lookup.get(sid) or {}
        name = str(rec.get("editor_name") or rec.get("name") or "")
        kw = _has_visual_keyword(name)
        if kw:
            hits.append({"source_id": sid, "editor_name": name, "keyword": kw})
    hits.sort(key=lambda h: h["source_id"])
    family_flag = bool(hits) and len(hits) == len(source_ids)
    if family_flag:
        reason = (
            f"all {len(hits)} source ids carry visual-only keywords "
            f"({', '.join(sorted({h['keyword'] for h in hits}))})"
        )
    else:
        reason = ""
    return family_flag, reason, hits


def _build_family(
    *,
    family_key: str,
    source_table: str,
    pak_type: int | None,
    pak_effect_order: int | None,
    buff_prefix: int | None,
    source_ids: list[int],
    record_lookup: dict[int, dict],
    pak: PakTables,
    desc_notes: dict[int, str],
    consumer_index: dict[int, list[dict]],
    team_used_skills: set[str],
    team_used_abilities: set[str],
    weather_ids: set[int],
    exact_emit_ids: set[int],
    exact_ignored_ids: set[int],
    ability_flag_ids: frozenset[int],
) -> dict:
    source_ids = sorted(source_ids)
    record_names = []
    for sid in source_ids:
        rec = record_lookup.get(sid) or {}
        name = str(rec.get("editor_name") or rec.get("name") or "")
        if name:
            record_names.append(name)
    editor_names = sorted(set(record_names))
    consumers = []
    for sid in source_ids:
        consumers.extend(consumer_index.get(sid, []))
    # Dedupe consumers by (kind, source_id).
    by_key: dict[tuple[str, int], dict] = {}
    for c in consumers:
        by_key.setdefault((c["kind"], c["source_id"]), c)
    consumer_records = list(by_key.values())
    sample_skill_consumers = _sample_sorted(
        [c for c in consumer_records if c["kind"] == "skill"]
    )
    sample_ability_consumers = _sample_sorted(
        [c for c in consumer_records if c["kind"] == "ability"]
    )
    used_consumer_count = sum(
        1
        for c in consumer_records
        if (c["kind"] == "skill" and c["name"] in team_used_skills)
        or (c["kind"] == "ability" and c["name"] in team_used_abilities)
    )
    breakdown = {
        "auto_structural_count": 0,
        "exact_jsonl_count": 0,
        "generated_weather_count": 0,
        "ignored_count": 0,
        "gap_count": 0,
        "ability_flag_count": 0,
    }
    for sid in source_ids:
        bucket = _classify_one_source_id(
            sid,
            pak=pak,
            weather_ids=weather_ids,
            exact_emit_ids=exact_emit_ids,
            exact_ignored_ids=exact_ignored_ids,
            ability_flag_ids=ability_flag_ids,
        )
        breakdown[bucket + "_count"] += 1
    coverage_status = _derive_coverage_status(breakdown)
    ignored_candidate, ignored_reason, ignored_source_hits = _ignored_candidate(
        source_ids, record_lookup,
    )
    pak_evidence: list[str] = []
    if source_table == "EFFECT_CONF":
        if source_ids:
            sid = source_ids[0]
            rec = record_lookup[sid]
            params = rec.get("effect_param") or []
            param_repr = [list(_vec_from_param_slot(s)) for s in params]
            pak_evidence.append(
                f"EFFECT_CONF.json: {sid} type={rec.get('type')} "
                f"effect_order={rec.get('effect_order')} "
                f"effect_param={json.dumps(param_repr, ensure_ascii=False)}"
            )
        pak_evidence.append("EFFECT_CONF.lua:L4-44 confirms field schema (id/type/effect_order/effect_param)")
    else:  # BUFF_CONF_DIRECT
        if source_ids:
            bid = source_ids[0]
            rec = record_lookup[bid]
            base_ids = [int(b) for b in (rec.get("buff_base_ids") or []) if b]
            pak_evidence.append(
                f"BUFF_CONF.json: {bid} buff_base_ids={base_ids} "
                f"editor_name={rec.get('editor_name', '')!r}"
            )
        pak_evidence.append("BUFF_CONF.lua confirms field schema (id/buff_base_ids/desc/...)")
    exact_jsonl_hits = sorted(eid for eid in source_ids if eid in exact_emit_ids)
    if exact_jsonl_hits:
        pak_evidence.append(
            f"exact_effects.jsonl emit rows for: {exact_jsonl_hits[:10]}"
        )
    weather_hits = sorted(eid for eid in source_ids if eid in weather_ids)
    if weather_hits:
        pak_evidence.append(
            f"generated/weather_decoders.py covers: {weather_hits[:10]}"
        )
    return {
        "family_key": family_key,
        "source_table": source_table,
        "pak_type": pak_type,
        "pak_effect_order": pak_effect_order,
        "buff_prefix": buff_prefix,
        "count": len(source_ids),
        "example_source_ids": source_ids[:5],
        "editor_names": editor_names,
        "param_shape": _collect_param_shape(source_ids, record_lookup, pak),
        "cross_refs": _cross_refs(source_ids, record_lookup, pak),
        "sample_skill_consumers": sample_skill_consumers,
        "sample_ability_consumers": sample_ability_consumers,
        "used_consumer_count": used_consumer_count,
        "desc_note_refs": _desc_note_refs(source_ids, record_lookup, pak.buff_conf, desc_notes),
        "coverage_status": coverage_status,
        "coverage_breakdown": breakdown,
        "pak_evidence": pak_evidence,
        "ignored_candidate": ignored_candidate,
        "ignored_candidate_reason": ignored_reason,
        "ignored_candidate_source_ids": ignored_source_hits,
    }


def build_families() -> list[dict]:
    pak = PakTables(PAK_DATA)
    desc_notes = _load_desc_notes()
    exact_emit_ids, exact_ignored_ids = _load_exact_rules()
    weather_ids = set(WEATHER_EFFECT_DECODERS.keys())
    ability_flag_rules = load_ability_flags_from_effects(effect_conf=pak.effect_conf)
    ability_flag_ids: frozenset[int] = frozenset(ability_flag_rules.keys())

    skills = _load_canonical("skills.jsonl")
    abilities = _load_canonical("abilities.jsonl")
    pets = _load_canonical("pets.jsonl")
    teams = _load_canonical("teams.jsonl")

    consumer_index = _build_consumer_index(skills, abilities)
    team_used_skills, team_used_abilities = _build_team_used(teams, pets)
    _validate_ability_flag_rules(
        ability_flag_rules,
        pak.effect_conf,
        consumer_index,
        exact_emit_ids,
        exact_ignored_ids,
        weather_ids,
    )

    families: list[dict] = []

    # EFFECT_CONF families — grouped by (type, effect_order).
    by_type_order: dict[tuple[int, int], list[int]] = defaultdict(list)
    for eid, rec in pak.effect_conf.items():
        key = (int(rec.get("type", 0)), int(rec.get("effect_order", 0)))
        by_type_order[key].append(eid)
    for (t, o), eids in by_type_order.items():
        families.append(_build_family(
            family_key=f"effect_conf:t{t}:o{o}",
            source_table="EFFECT_CONF",
            pak_type=t,
            pak_effect_order=o,
            buff_prefix=None,
            source_ids=eids,
            record_lookup=pak.effect_conf,
            pak=pak,
            desc_notes=desc_notes,
            consumer_index=consumer_index,
            team_used_skills=team_used_skills,
            team_used_abilities=team_used_abilities,
            weather_ids=weather_ids,
            exact_emit_ids=exact_emit_ids,
            exact_ignored_ids=exact_ignored_ids,
            ability_flag_ids=ability_flag_ids,
        ))

    # BUFF_CONF_DIRECT families — every skill_result effect_id that exists
    # in BUFF_CONF but not in EFFECT_CONF, grouped by classifier gap
    # primitive (base_ids[0] // 1000 — never buff_id // 1000).
    direct_buff_ids: set[int] = set()
    for eid in consumer_index:
        if eid in pak.effect_conf:
            continue
        if eid in pak.buff_conf:
            direct_buff_ids.add(eid)
    by_buff_family: dict[tuple[str, int | None], list[int]] = defaultdict(list)
    for bid in direct_buff_ids:
        family_key, prefix = _buff_family_key(bid, pak.buff_conf)
        by_buff_family[(family_key, prefix)].append(bid)
    for (family_key, prefix), bids in by_buff_family.items():
        families.append(_build_family(
            family_key=family_key,
            source_table="BUFF_CONF_DIRECT",
            pak_type=None,
            pak_effect_order=None,
            buff_prefix=prefix,
            source_ids=bids,
            record_lookup=pak.buff_conf,
            pak=pak,
            desc_notes=desc_notes,
            consumer_index=consumer_index,
            team_used_skills=team_used_skills,
            team_used_abilities=team_used_abilities,
            weather_ids=weather_ids,
            exact_emit_ids=exact_emit_ids,
            exact_ignored_ids=exact_ignored_ids,
            ability_flag_ids=ability_flag_ids,
        ))

    families.sort(key=lambda f: f["family_key"])
    return families
