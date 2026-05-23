"""Per-family record assembly + the ``build_families()`` driver.

``_build_family`` constructs one catalog dict from a list of source ids.
``build_families`` is the top-level orchestrator: load pak + canonical,
build consumer / team indices, run the ability-flag cross-check, then
emit one record per EFFECT_CONF (type, effect_order) bucket and one per
BUFF_CONF_DIRECT prefix bucket.

Helper functions live in sibling modules grouped by responsibility:

* :mod:`.params`   — pak ``effect_param`` shape (``_collect_param_shape``)
                     and the underlying ``_vec_from_param_slot``.
* :mod:`.refs`     — cross-reference / desc-note extraction
                     (``_cross_refs``, ``_desc_note_refs``,
                     ``_sample_sorted``).
* :mod:`.classify` — coverage bucketing per source id.
* :mod:`.consumers`/ :mod:`.io` / :mod:`.validation` — preload helpers.
"""

from __future__ import annotations

import json
from collections import defaultdict

from roco.compiler_v2.effect_codegen.ability_flags_from_effects import (
    load_ability_flags_from_effects,
)
from roco.compiler_v2.effect_codegen.pak import PakTables
from roco.generated.weather_decoders import WEATHER_EFFECT_DECODERS

from .classify import (
    _buff_family_key,
    _classify_one_source_id,
    _derive_coverage_status,
)
from .consumers import _build_consumer_index, _build_team_used
from .io import _load_canonical, _load_desc_notes, _load_exact_rules
from .params import _collect_param_shape, _vec_from_param_slot
from .paths import PAK_DATA
from .refs import _cross_refs, _desc_note_refs, _sample_sorted
from .validation import _validate_ability_flag_rules


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
        "exact_semantic_count": 0,
        "generated_weather_count": 0,
        "gap_count": 0,
        "ability_flag_count": 0,
    }
    for sid in source_ids:
        bucket = _classify_one_source_id(
            sid,
            pak=pak,
            weather_ids=weather_ids,
            exact_emit_ids=exact_emit_ids,
            ability_flag_ids=ability_flag_ids,
        )
        breakdown[bucket + "_count"] += 1
    coverage_status = _derive_coverage_status(breakdown)
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
    exact_semantic_hits = sorted(eid for eid in source_ids if eid in exact_emit_ids)
    if exact_semantic_hits:
        pak_evidence.append(
            f"compiler_v2 exact semantic rows for: {exact_semantic_hits[:10]}"
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
    }


def build_families() -> list[dict]:
    pak = PakTables(PAK_DATA)
    desc_notes = _load_desc_notes()
    exact_emit_ids = _load_exact_rules()
    weather_ids = set(WEATHER_EFFECT_DECODERS.keys())
    ability_flag_rules = load_ability_flags_from_effects(
        effect_conf=pak.effect_conf,
        buff_conf=pak.buff_conf,
    )
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
        pak.buff_conf,
        consumer_index,
        exact_emit_ids,
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
            ability_flag_ids=ability_flag_ids,
        ))

    families.sort(key=lambda f: f["family_key"])
    return families
