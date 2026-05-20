"""Build the pak effect family catalog.

Produces two artifacts:

* ``roco/compiler/rules/effect_families.jsonl`` — one JSON line per family
  (``(pak_type, pak_effect_order)`` for EFFECT_CONF references; buff-prefix
  bucket for direct BUFF_CONF references in skill_result).  Schema doc lives
  in the project plan.
* ``_docs/effect_family_audit.md`` — same content rendered for human review.

The catalog is **not** a rule file — it has no ``handler`` field.  Its job is
to document, per family, the pak evidence (parameter shapes, cross-refs,
sample consumers, decoder-path coverage breakdown) that future kernel work
needs.  Every string field is sourced from pak/Lua data tables or the
project's own rule files — no speculation, no ``likely`` / ``would`` /
``probably`` / ``possibly``.

Run::

    uv run python -m roco.compiler.build_effect_families         # write
    uv run python -m roco.compiler.build_effect_families --check # CI gate
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from roco.compiler.effect_codegen.classify import decode_buff_direct, decode_effect
from roco.compiler.effect_codegen.exact_decoders import decode_exact
from roco.compiler.effect_codegen.outcomes import (
    EmitOutcome,
    GapOutcome,
    IgnoredOutcome,
)
from roco.compiler.effect_codegen.pak import PakTables
from roco.generated.weather_decoders import WEATHER_EFFECT_DECODERS


# ── paths (no compiler→data reverse imports) ───────────────────────────────

ROOT = Path(__file__).resolve().parents[2]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data"
EXACT_RULES_PATH = ROOT / "roco" / "compiler" / "rules" / "exact_effects.jsonl"
CATALOG_JSONL = ROOT / "roco" / "compiler" / "rules" / "effect_families.jsonl"
CATALOG_MD = ROOT / "_docs" / "effect_family_audit.md"
CANONICAL_DIR = ROOT / "_data" / "canonical"


# ── enums + constants ──────────────────────────────────────────────────────

COVERAGE_STATUSES = frozenset({
    "auto_structural",
    "exact_jsonl",
    "exact_jsonl_partial",
    "generated_weather",
    "ignored",
    "gap",
    "mixed",
})

# Editor-name keywords that mark a pak effect as visual-only candidate.
# Only flags — Phase 1 does NOT promote these to ignored rules.
VISUAL_KEYWORDS = ("动效", "飘字", "动画", "特效")

DESC_ID_RE = re.compile(r"<desc_id=(\d+)>")


# ── pak helpers (local, no roco.data imports) ──────────────────────────────


def _load_pak_table(path: Path) -> dict[int, dict]:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def _load_desc_notes() -> dict[int, str]:
    """Read DESC_NOTE_CONF.json directly (no parse_pak import)."""
    rows = _load_pak_table(PAK_DATA / "BinData" / "DESC_NOTE_CONF.json")
    return {int(k): str(rec.get("note", "")) for k, rec in rows.items()}


def _load_canonical(name: str) -> list[dict]:
    path = CANONICAL_DIR / name
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if raw:
                out.append(json.loads(raw))
    return out


# ── exact_effects loader (file scan; no behavioural reuse needed) ──────────


def _load_exact_rules() -> tuple[set[int], set[int]]:
    """Return (exact_emit_ids, exact_ignored_ids) from the JSONL source."""
    emit: set[int] = set()
    ignored: set[int] = set()
    with EXACT_RULES_PATH.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            eid = int(rec["effect_id"])
            if rec.get("kind", "emit") == "ignored":
                ignored.add(eid)
            else:
                emit.add(eid)
    return emit, ignored


# ── reverse-consumer indexes ──────────────────────────────────────────────


def _collect_consumer(record: dict, kind: str) -> dict:
    """Project a skills/abilities canonical row into a compact consumer dict."""
    source_fields = record.get("source_fields") or {}
    return {
        "kind": kind,  # 'skill' / 'ability'
        "source_id": int(record.get("source_id") or source_fields.get("id") or 0),
        "name": str(record.get("name", "")),
        "desc": str(source_fields.get("desc", "")),
    }


def _consumer_skill_results(record: dict) -> list[dict]:
    """Pick the skill_result / effect_list list from a canonical row."""
    source_fields = record.get("source_fields") or {}
    rows = source_fields.get("skill_result") or source_fields.get("effect_list") or []
    return [entry for entry in rows if isinstance(entry, dict) and entry.get("effect_id")]


def _build_consumer_index(
    skills: list[dict],
    abilities: list[dict],
) -> dict[int, list[dict]]:
    """``effect_id → [consumer entry, ...]`` — one entry per consuming skill/ability.

    Each consumer entry carries the original ``skill_result_entry`` so the
    catalog can show cast_moment / target / success_rate context.
    """
    out: dict[int, list[dict]] = defaultdict(list)
    for record, kind in [(s, "skill") for s in skills] + [(a, "ability") for a in abilities]:
        head = _collect_consumer(record, kind)
        for entry in _consumer_skill_results(record):
            eid = int(entry["effect_id"])
            out[eid].append({**head, "skill_result_entry": entry})
    return out


def _build_team_used(teams: list[dict], pets: list[dict]) -> tuple[set[str], set[str]]:
    """Return (team_used_skill_names, team_used_ability_names) by canonical name.

    Mirrors :func:`roco.data.import_db.import_teams` pet resolution: a team
    pet's full descriptive ``name`` (e.g. ``星光狮（月光能量的样子）``) often
    has no canonical match because pets.jsonl carries form-stripped names
    like ``星光狮``.  Fall back to the team pet's ``name_short`` so ability
    lookups don't drop ~22 form-suffixed pet abilities (化茧 / 电流刺激 …).
    """
    used_skill_names: set[str] = set()
    used_pet_lookup_keys: set[str] = set()
    for team in teams:
        for pet in team.get("pets") or []:
            full_name = str(pet.get("name", ""))
            short_name = str(pet.get("name_short", ""))
            if full_name:
                used_pet_lookup_keys.add(full_name)
            if short_name and short_name != full_name:
                used_pet_lookup_keys.add(short_name)
            for move in pet.get("moves") or []:
                if isinstance(move, str):
                    used_skill_names.add(move)
                elif isinstance(move, dict) and move.get("name"):
                    used_skill_names.add(str(move["name"]))
    # Canonical pet → ability: index by ``name`` AND ``display_name`` so the
    # name_short fallback chain can hit either key (parse_pak emits both for
    # form variants).
    ability_by_pet_name: dict[str, str] = {}
    for pet in pets:
        ability = pet.get("ability")
        if not ability:
            continue
        for key in (pet.get("name"), pet.get("display_name")):
            if key:
                ability_by_pet_name.setdefault(str(key), str(ability))
    used_ability_names = {
        ability_by_pet_name[name]
        for name in used_pet_lookup_keys
        if name in ability_by_pet_name
    }
    return used_skill_names, used_ability_names


# ── per-family computation ────────────────────────────────────────────────


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


def _classify_one_source_id(
    sid: int,
    *,
    pak: PakTables,
    weather_ids: set[int],
    exact_emit_ids: set[int],
    exact_ignored_ids: set[int],
) -> str:
    """Run the actual decoder path and report which bucket ``sid`` falls in.

    Order matters: ``decode_exact`` wins first (exact_jsonl / ignored / weather);
    fall back to structural decode for EFFECT_CONF and direct BUFF_CONF refs.
    """
    if sid in weather_ids:
        return "generated_weather"
    if sid in exact_ignored_ids:
        return "ignored"
    if sid in exact_emit_ids:
        return "exact_jsonl"
    # Defensive: decode_exact may still return something (e.g. compound),
    # though the two id sets above are derived from the same JSONL.
    override = decode_exact(sid)
    if override is not None:
        if isinstance(override, IgnoredOutcome):
            return "ignored"
        return "exact_jsonl"
    if sid in pak.effect_conf:
        outcomes = decode_effect(sid, pak.effect_conf, pak.buff_conf)
    elif sid in pak.buff_conf:
        outcomes = decode_buff_direct(sid, pak.buff_conf)
    else:
        return "gap"
    has_emit = any(isinstance(o, EmitOutcome) for o in outcomes)
    has_gap = any(isinstance(o, GapOutcome) for o in outcomes)
    if has_emit and not has_gap:
        return "auto_structural"
    return "gap"


def _derive_coverage_status(breakdown: dict[str, int]) -> str:
    nonzero = {k: v for k, v in breakdown.items() if v > 0}
    if not nonzero:
        return "gap"
    if len(nonzero) == 1:
        only = next(iter(nonzero))
        return {
            "auto_structural_count": "auto_structural",
            "exact_jsonl_count": "exact_jsonl",
            "generated_weather_count": "generated_weather",
            "ignored_count": "ignored",
            "gap_count": "gap",
        }[only]
    if set(nonzero) == {"exact_jsonl_count", "gap_count"}:
        return "exact_jsonl_partial"
    return "mixed"


def _buff_family_key(buff_id: int, buff_conf: dict[int, dict]) -> tuple[str, int | None]:
    """Map a direct BUFF_CONF id to (family_key, base_id_prefix).

    Reuses the gap-primitive logic from :func:`classify._buff_gap`: first
    non-zero ``buff_base_id`` divided by 1000 — *not* ``buff_id // 1000``.
    """
    rec = buff_conf.get(buff_id)
    if rec is None:
        return f"buff_conf_direct:buff_{buff_id}", None
    base_ids = [int(b) for b in (rec.get("buff_base_ids") or []) if b]
    if not base_ids:
        return "buff_conf_direct:buff_no_base_ids", None
    prefix = base_ids[0] // 1000
    return f"buff_conf_direct:prefix_{prefix}", prefix


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
    }
    for sid in source_ids:
        bucket = _classify_one_source_id(
            sid,
            pak=pak,
            weather_ids=weather_ids,
            exact_emit_ids=exact_emit_ids,
            exact_ignored_ids=exact_ignored_ids,
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


# ── top-level assembly ────────────────────────────────────────────────────


def build_families() -> list[dict]:
    pak = PakTables(PAK_DATA)
    desc_notes = _load_desc_notes()
    exact_emit_ids, exact_ignored_ids = _load_exact_rules()
    weather_ids = set(WEATHER_EFFECT_DECODERS.keys())

    skills = _load_canonical("skills.jsonl")
    abilities = _load_canonical("abilities.jsonl")
    pets = _load_canonical("pets.jsonl")
    teams = _load_canonical("teams.jsonl")

    consumer_index = _build_consumer_index(skills, abilities)
    team_used_skills, team_used_abilities = _build_team_used(teams, pets)

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
        ))

    families.sort(key=lambda f: f["family_key"])
    return families


# ── rendering ─────────────────────────────────────────────────────────────


def render_jsonl(families: list[dict]) -> str:
    return "\n".join(json.dumps(f, ensure_ascii=False, sort_keys=True) for f in families) + "\n"


def render_markdown(families: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Effect Family Audit\n")
    lines.append(
        "_Auto-generated by `roco/compiler/build_effect_families.py`. "
        "Do not edit by hand. Re-run with `uv run python -m roco.compiler.build_effect_families`._\n"
    )
    lines.append(f"Total families: **{len(families)}**\n")
    by_status: dict[str, int] = defaultdict(int)
    for f in families:
        by_status[f["coverage_status"]] += 1
    lines.append("## Coverage status\n")
    for status in sorted(by_status):
        lines.append(f"- `{status}`: {by_status[status]}")
    lines.append("")
    for f in families:
        lines.append(f"## `{f['family_key']}` — {f['source_table']}")
        lines.append("")
        lines.append(f"- count: **{f['count']}** | coverage: `{f['coverage_status']}` "
                     f"| used_consumer_count: {f['used_consumer_count']}")
        if f["editor_names"]:
            lines.append(f"- editor_names: {', '.join(f['editor_names'][:10])}")
        lines.append(f"- example_source_ids: {f['example_source_ids']}")
        lines.append(f"- coverage_breakdown: {f['coverage_breakdown']}")
        if f["sample_skill_consumers"]:
            lines.append("- sample_skill_consumers:")
            for c in f["sample_skill_consumers"]:
                lines.append(f"    - `{c['source_id']}` {c['name']} — {c['desc'][:80]}")
        if f["sample_ability_consumers"]:
            lines.append("- sample_ability_consumers:")
            for c in f["sample_ability_consumers"]:
                lines.append(f"    - `{c['source_id']}` {c['name']} — {c['desc'][:80]}")
        if f["desc_note_refs"]:
            lines.append("- desc_note_refs:")
            for d in f["desc_note_refs"]:
                lines.append(f"    - `desc_{d['desc_id']}` {d['note']}")
        if f["pak_evidence"]:
            lines.append("- pak_evidence:")
            for e in f["pak_evidence"]:
                lines.append(f"    - {e}")
        if f["ignored_candidate"]:
            lines.append(f"- **ignored_candidate (whole family)**: {f['ignored_candidate_reason']}")
        if f.get("ignored_candidate_source_ids"):
            lines.append("- ignored_candidate_source_ids:")
            for hit in f["ignored_candidate_source_ids"]:
                lines.append(
                    f"    - `{hit['source_id']}` {hit['editor_name']} "
                    f"(keyword `{hit['keyword']}`)"
                )
        lines.append("")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if on-disk catalog differs from a fresh build",
    )
    args = parser.parse_args(argv)

    families = build_families()
    new_jsonl = render_jsonl(families)
    new_md = render_markdown(families)

    if args.check:
        return _check(new_jsonl, new_md)
    CATALOG_JSONL.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_MD.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_JSONL.write_text(new_jsonl, encoding="utf-8")
    CATALOG_MD.write_text(new_md, encoding="utf-8")
    print(f"effect_families.jsonl: {len(families)} families -> {CATALOG_JSONL}")
    print(f"effect_family_audit.md -> {CATALOG_MD}")
    return 0


def _check(new_jsonl: str, new_md: str) -> int:
    drift: list[str] = []
    for path, fresh in ((CATALOG_JSONL, new_jsonl), (CATALOG_MD, new_md)):
        if not path.exists():
            drift.append(f"missing: {path}")
            continue
        on_disk = path.read_text(encoding="utf-8")
        if on_disk != fresh:
            drift.append(f"stale: {path}")
    if drift:
        sys.stderr.write(
            "effect family catalog is out of date; re-run "
            "`uv run python -m roco.compiler.build_effect_families`:\n"
        )
        for d in drift:
            sys.stderr.write(f"  - {d}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
