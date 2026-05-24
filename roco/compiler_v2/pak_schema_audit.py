"""Pak schema mining (read-only).

Inventories the structural axes pak already exposes — EFFECT_CONF's
``(type, effect_order)`` and BUFFBASE_CONF's ``buffbase_order`` — and
labels remaining engine/compiler semantic coverage against those axes.
The output is purely
descriptive: this module does **not** mutate any rule file, regenerate
codegen, or change kernel behavior.  Its job is to expose how much of
the current semantic debt is structurally addressable in pak and
therefore collapsible into family decoders in future phases.

Outputs::

    _docs/pak_schema_audit.md

Run::

    uv run python -m roco.compiler_v2.pak_schema_audit         # write
    uv run python -m roco.compiler_v2.pak_schema_audit --check # CI gate

``--check`` returns 1 if the on-disk audit file differs from a fresh
build — equivalent to ``build_effect_families --check``.  The schema
drift section is informational; drift between Lua schema and JSON
record fields is reported but does not by itself fail ``--check`` (the
drift snapshot is part of the audit body and stale only if the audit
file itself is stale).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from roco.data.canonical import canonical_list
from roco.compiler_v2.handler_registry import func_to_const, load_handler_indices
from roco.compiler_v2.effect_families.paths import CATALOG_JSONL as EFFECT_FAMILIES_JSONL

# Repo root: roco/compiler_v2/pak_schema_audit.py -> parents[2]
ROOT = Path(__file__).resolve().parents[2]
PAK_BIN = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
PAK_LUA = ROOT / "pak-public-kit" / "output" / "scripts" / "lua" / "Data" / "tinyio_Config"
RULES_DIR = ROOT / "roco" / "compiler_v2" / "rules"
AUDIT_MD = ROOT / "_docs" / "pak_schema_audit.md"

# (logical_name, lua_filename, json_filename) — the pak tables we mine.
SCHEMA_TABLES: tuple[tuple[str, str, str], ...] = (
    ("EFFECT_CONF",   "EFFECT_CONF.lua",   "EFFECT_CONF.json"),
    ("BUFFBASE_CONF", "BUFFBASE_CONF.lua", "BUFFBASE_CONF.json"),
    ("BUFF_CONF",     "BUFF_CONF.lua",     "BUFF_CONF.json"),
    ("SKILL_CONF",    "SKILL_CONF.lua",    "SKILL_CONF.json"),
)

# Lua-schema-field detection: both direct-scalar assignment and the
# table.insert-loop pattern used for array-typed columns.
_LUA_DIRECT_FIELD_RE = re.compile(r"\blua_record\.(\w+)\s*=\s*r\.(\w+)\b")
_LUA_LOOP_FIELD_RE = re.compile(r"\bfor\s+i\s*=\s*0\s*,\s*#r\.(\w+)\s*-\s*1\b")


# ── pak loaders ───────────────────────────────────────────────────


def _load_pak_table(path: Path) -> dict[int, dict[str, Any]]:
    """Read a pak BinData JSON file and return it keyed by integer id."""
    with path.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)
    rows = raw.get("RocoDataRows", raw)
    return {int(k): v for k, v in rows.items()}


def _parse_lua_schema_fields(lua_path: Path) -> set[str]:
    """Extract top-level field names tracked by a *_CONF.lua loader.

    Captures both the direct-scalar form (``lua_record.X = r.X``) and
    the loop-header form used for array-typed columns
    (``for i = 0, #r.X - 1 do``).  Misses fields populated via paths
    other than those two — acceptable for the drift report, which is
    informational rather than authoritative.
    """
    text = lua_path.read_text(encoding="utf-8")
    fields = {m.group(2) for m in _LUA_DIRECT_FIELD_RE.finditer(text)}
    fields.update(m.group(1) for m in _LUA_LOOP_FIELD_RE.finditer(text))
    return fields


def _scan_json_fields(json_path: Path) -> set[str]:
    """Union of top-level keys across every record in a pak JSON table."""
    rows = _load_pak_table(json_path)
    fields: set[str] = set()
    for rec in rows.values():
        if isinstance(rec, dict):
            fields.update(rec.keys())
    return fields


# ── schema drift ──────────────────────────────────────────────────


def detect_schema_drift() -> list[dict]:
    """For each tracked pak table, diff Lua schema fields vs JSON fields.

    Returns one dict per table with sets for shared / lua_only /
    json_only.  ``lua_only`` typically reflects JSON omitting
    default/null values; ``json_only`` typically reflects pak adding a
    new column that the Lua schema generator did not regenerate.  Both
    are surfaced for review.
    """
    out: list[dict] = []
    for name, lua_fn, json_fn in SCHEMA_TABLES:
        lua_fields = _parse_lua_schema_fields(PAK_LUA / lua_fn)
        json_fields = _scan_json_fields(PAK_BIN / json_fn)
        out.append({
            "table": name,
            "shared_count": len(lua_fields & json_fields),
            "lua_only": sorted(lua_fields - json_fields),
            "json_only": sorted(json_fields - lua_fields),
        })
    return out


# ── canonical / catalog loaders ───────────────────────────────────


def _load_canonical(name: str) -> list[dict]:
    return canonical_list(name)


def _build_consumer_counts(
    skills: list[dict],
    abilities: list[dict],
) -> tuple[dict[int, int], dict[int, int]]:
    """For each effect_id consumed by canonical skills/abilities, count refs."""
    skill_users: defaultdict[int, int] = defaultdict(int)
    ability_users: defaultdict[int, int] = defaultdict(int)
    for canonical, counter in ((skills, skill_users), (abilities, ability_users)):
        for rec in canonical:
            source = rec.get("source_fields") or {}
            for field in ("skill_result", "effect_list"):
                rows = source.get(field) or []
                for entry in rows:
                    if isinstance(entry, dict) and entry.get("effect_id"):
                        counter[int(entry["effect_id"])] += 1
    return dict(skill_users), dict(ability_users)


def _load_effect_families() -> dict[str, dict]:
    """Return {family_key: family_record} from the existing catalog."""
    out: dict[str, dict] = {}
    if not EFFECT_FAMILIES_JSONL.exists():
        return out
    with EFFECT_FAMILIES_JSONL.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                rec = json.loads(line)
                out[rec["family_key"]] = rec
    return out


def _load_exact_rules() -> list[dict]:
    """Return active exact compiler rules.

    The replacement compiler no longer keeps hand-written effect_id
    runtime rows.  Structural family decoders and generated tables own
    this coverage now, so the audit should report an empty debt table.
    """

    return []


def _handler_indices() -> dict[str, int]:
    return load_handler_indices()


def _load_handler_axis_rules() -> tuple[dict[int, dict], dict[int, dict], list[dict]]:
    """Return (buffbase_order_rules, prefix_rules, legacy_base_id_overrides).

    The active source is engine-owned ``op_meta`` decorator metadata.
    ``handles_buff`` / ``handles_prefix`` store ``Enum.BuffType`` symbols,
    so this helper resolves symbols through the current Lua static bundle.
    """

    from roco.compiler_v2.build import build_static_bundle
    from roco.compiler_v2.handler_axes import resolve_handler_axes

    bundle = build_static_bundle()
    resolved = resolve_handler_axes(_handler_indices(), bundle.lua_enums)
    buff_type_enum = bundle.lua_enums["BuffType"]

    by_order: dict[int, dict] = {}
    for symbol, (handler_name, alias) in resolved.raw["buff_type"].items():
        order = int(buff_type_enum[str(symbol)])
        by_order[order] = {
            "buffbase_order": order,
            "buff_type": symbol,
            "handler": func_to_const(handler_name),
            "alias": alias,
            "source": "engine_op_meta",
        }

    by_prefix: dict[int, dict] = {}
    for symbol, (handler_name, alias) in resolved.raw["prefix_type"].items():
        prefix = 2000 + int(buff_type_enum[str(symbol)])
        by_prefix[prefix] = {
            "prefix": prefix,
            "buff_type": symbol,
            "handler": func_to_const(handler_name),
            "alias": alias,
            "source": "engine_op_meta",
        }

    overrides: list[dict] = []
    for base_id, (handler_name, note) in resolved.raw.get("base_id", {}).items():
        overrides.append({
            "base_id": int(base_id),
            "handler": func_to_const(handler_name),
            "note": note,
            "source": "engine_op_meta",
        })
    return by_order, by_prefix, sorted(overrides, key=lambda r: r["base_id"])


def _load_prefix_rules() -> tuple[dict[int, dict], list[dict]]:
    _order_rules, prefix_rules, overrides = _load_handler_axis_rules()
    return prefix_rules, overrides


def _load_buffbase_order_rules() -> dict[int, dict]:
    buffbase_order_rules, _prefix_rules, _overrides = _load_handler_axis_rules()
    return buffbase_order_rules


# ── EFFECT_CONF families ──────────────────────────────────────────


def _effect_param_shape(records: list[dict]) -> dict:
    """Summarize ``effect_param`` slot-count distribution + slot[0] type."""
    slot_counts: Counter = Counter()
    slot0_types: Counter = Counter()
    for rec in records:
        params = rec.get("effect_param") or []
        slot_counts[len(params)] += 1
        if params and isinstance(params[0], dict):
            inner = params[0].get("params") or []
            if inner:
                slot0_types[type(inner[0]).__name__] += 1
    return {
        "slot_count": dict(sorted(slot_counts.items())),
        "slot0_value_types": dict(sorted(slot0_types.items())),
    }


def effect_conf_families(
    effect_conf: dict[int, dict],
    skill_users: dict[int, int],
    ability_users: dict[int, int],
    catalog: dict[str, dict],
) -> list[dict]:
    """One row per ``(type, effect_order)``.  See module docstring."""
    by_type_order: defaultdict[tuple[int, int], list[tuple[int, dict]]] = defaultdict(list)
    for eid, rec in effect_conf.items():
        t = int(rec.get("type", 0))
        o = int(rec.get("effect_order", 0))
        by_type_order[(t, o)].append((eid, rec))
    out: list[dict] = []
    for (t, o), entries in by_type_order.items():
        records = [r for _, r in entries]
        names = sorted({
            r.get("editor_name") or r.get("name") or ""
            for r in records
            if r.get("editor_name") or r.get("name")
        })
        family_key = f"effect_conf:t{t}:o{o}"
        catalog_rec = catalog.get(family_key, {})
        out.append({
            "type": t,
            "effect_order": o,
            "family_key": family_key,
            "count": len(entries),
            "param_shape": _effect_param_shape(records),
            "editor_name_samples": names[:8],
            "consumer_skills": sum(skill_users.get(eid, 0) for eid, _ in entries),
            "consumer_abilities": sum(ability_users.get(eid, 0) for eid, _ in entries),
            "current_coverage_status": catalog_rec.get("coverage_status", "unknown"),
            "current_coverage_breakdown": catalog_rec.get("coverage_breakdown", {}),
        })
    out.sort(key=lambda r: (r["type"], r["effect_order"]))
    return out


# ── BUFFBASE_CONF families ────────────────────────────────────────


def buffbase_families(
    buffbase_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    prefix_rules: dict[int, dict],
    buffbase_order_rules: dict[int, dict] | None = None,
) -> list[dict]:
    """One row per ``buffbase_order``.

    For each order the report includes: how many BUFFBASE_CONF records
    share it, their ``buffbase_param`` slot-count distribution, the
    distribution of ``trigger_type`` (numeric) and which prefix bucket
    each base_id lives in.  Cross-references both rule files:

    * ``covering_buffbase_order_rule`` — the primary engine
      ``handles_buff`` axis resolved through ``Enum.BuffType``.
    * ``covering_prefix_rule`` — the mixed-prefix engine axis; reports
      the dominant prefix that nominally covers this order.
    """
    if buffbase_order_rules is None:
        buffbase_order_rules = {}
    by_order: defaultdict[int, list[tuple[int, dict]]] = defaultdict(list)
    for bid, rec in buffbase_conf.items():
        order = int(rec.get("buffbase_order", 0))
        by_order[order].append((bid, rec))

    # Reverse map: which BUFF_CONF ids reference each base_id?
    refs_by_base_id: defaultdict[int, set[int]] = defaultdict(set)
    for buff_id, rec in buff_conf.items():
        for b in (rec.get("buff_base_ids") or []):
            if int(b):
                refs_by_base_id[int(b)].add(int(buff_id))

    out: list[dict] = []
    for order in sorted(by_order):
        entries = by_order[order]
        param_slot_counts: Counter = Counter()
        trigger_types: Counter = Counter()
        prefix_distribution: Counter = Counter()
        referencing_buff_ids: set[int] = set()
        for bid, r in entries:
            param_slot_counts[len(r.get("buffbase_param") or [])] += 1
            tt = r.get("trigger_type")
            if tt is not None:
                trigger_types[int(tt)] += 1
            prefix_distribution[int(bid) // 1000] += 1
            referencing_buff_ids.update(refs_by_base_id.get(bid, set()))

        # Most-frequent prefix that ALSO has a handler rule, if any.
        covering: dict | None = None
        total_prefix_count = sum(prefix_distribution.values())
        for prefix, count in prefix_distribution.most_common():
            if prefix in prefix_rules:
                rule = prefix_rules[prefix]
                covering = {
                    "prefix": prefix,
                    "handler": rule["handler"],
                    "alias": rule.get("alias"),
                    "share": f"{count}/{total_prefix_count}",
                }
                break

        names = sorted({
            r.get("editor_name")
            for _, r in entries
            if r.get("editor_name")
        })
        covering_order = buffbase_order_rules.get(order)
        out.append({
            "buffbase_order": order,
            "count": len(entries),
            "param_slot_count": dict(sorted(param_slot_counts.items())),
            "trigger_types": dict(sorted(trigger_types.items())),
            "prefix_distribution": dict(sorted(prefix_distribution.items())),
            "referencing_buff_ids_count": len(referencing_buff_ids),
            "covering_buffbase_order_rule": (
                {
                    "handler": covering_order["handler"],
                    "alias": covering_order.get("alias"),
                }
                if covering_order
                else None
            ),
            "covering_prefix_rule": covering,
            "editor_name_samples": names[:5],
        })
    return out


# ── rule debt ─────────────────────────────────────────────────────


def exact_rule_debt(
    exact_rules: list[dict],
    effect_conf: dict[int, dict],
    cluster_threshold: int = 3,
) -> list[dict]:
    """Annotate each exact rule with its EFFECT_CONF.effect_order and
    flag (effect_order, handler) clusters above ``cluster_threshold``
    as migration candidates."""
    cluster_counts: defaultdict[tuple[int, str], int] = defaultdict(int)
    annotated: list[dict] = []
    for rec in exact_rules:
        eid = int(rec["effect_id"])
        handler = rec["handler"]
        pak_rec = effect_conf.get(eid, {})
        order = int(pak_rec.get("effect_order", -1)) if pak_rec else -1
        pak_type = int(pak_rec.get("type", -1)) if pak_rec else -1
        annotated.append({
            "effect_id": eid,
            "handler": handler,
            "pak_type": pak_type,
            "effect_order": order,
            "pak_editor_name": rec.get("pak_editor_name", ""),
            "args": rec.get("args"),
        })
        cluster_counts[(order, handler)] += 1
    for entry in annotated:
        size = cluster_counts[(entry["effect_order"], entry["handler"])]
        entry["cluster_size"] = size
        entry["migration_candidate"] = (
            entry["effect_order"] >= 0 and size >= cluster_threshold
        )
    return annotated


def prefix_rule_debt(
    prefix_rules: dict[int, dict],
    buffbase_conf: dict[int, dict],
) -> list[dict]:
    """For each prefix rule, compute dominant ``buffbase_order`` and
    concentration.  ``clean_rewrite=True`` means every base_id with
    that prefix has the dominant order; ``implied_identity`` flags the
    structural-coincidence rule ``prefix - 2000 == buffbase_order``.
    """
    by_prefix: defaultdict[int, Counter] = defaultdict(Counter)
    for bid, rec in buffbase_conf.items():
        order = rec.get("buffbase_order")
        if order is None:
            continue
        by_prefix[int(bid) // 1000][int(order)] += 1

    out: list[dict] = []
    for prefix in sorted(prefix_rules):
        rule = prefix_rules[prefix]
        dist = by_prefix.get(prefix, Counter())
        total = sum(dist.values())
        if total == 0:
            out.append({
                "prefix": prefix,
                "handler": rule["handler"],
                "alias": rule.get("alias"),
                "dominant_buffbase_order": None,
                "concentration": 0.0,
                "distribution": {},
                "clean_rewrite": False,
                "implied_identity": False,
                "note": "no BUFFBASE_CONF record with this prefix",
            })
            continue
        top, top_n = dist.most_common(1)[0]
        concentration = top_n / total
        out.append({
            "prefix": prefix,
            "handler": rule["handler"],
            "alias": rule.get("alias"),
            "dominant_buffbase_order": top,
            "concentration": round(concentration, 4),
            "distribution": dict(sorted(dist.items())),
            "clean_rewrite": (concentration == 1.0),
            "implied_identity": (top == prefix - 2000),
        })
    return out


# ── render ────────────────────────────────────────────────────────


def _fmt_dict_inline(d: dict) -> str:
    """Render `{1: 7, 2: 3}` -> `1:7, 2:3` (sorted, deterministic)."""
    if not d:
        return "—"
    return ", ".join(f"{k}:{v}" for k, v in sorted(d.items()))


def render_markdown(
    drift: list[dict],
    effect_families: list[dict],
    buffbase_fams: list[dict],
    exact_debt: list[dict],
    prefix_debt: list[dict],
) -> str:
    lines: list[str] = []
    lines.append("# Pak Schema Audit")
    lines.append("")
    lines.append(
        "_Auto-generated by `roco/compiler_v2/pak_schema_audit.py`. "
        "Do not edit by hand. Re-run with "
        "`uv run python -m roco.compiler_v2.pak_schema_audit`._"
    )
    lines.append("")
    lines.append(
        "Read-only inventory of pak's structural axes "
        "(EFFECT_CONF.effect_order, BUFFBASE_CONF.buffbase_order) "
        "and a debt assessment of hand-written rules against those axes. "
        "This document does not drive runtime behavior — it informs "
        "future family-decoder work."
    )
    lines.append("")

    # ── Section 1: schema drift ──
    lines.append("## 1. Schema drift")
    lines.append("")
    lines.append(
        "Comparison of Lua schema fields (parsed from `*_CONF.lua` "
        "loaders) vs JSON record fields (union across all rows). "
        "**Lua-only** typically means a default-valued field omitted "
        "from JSON. **JSON-only** means the Lua schema generator did "
        "not track a column pak now exposes — usually the more "
        "interesting case."
    )
    lines.append("")
    lines.append("| table | shared | lua-only | json-only |")
    lines.append("|---|---:|---|---|")
    for d in drift:
        lo = ", ".join(d["lua_only"]) if d["lua_only"] else "—"
        jo = ", ".join(d["json_only"]) if d["json_only"] else "—"
        lines.append(f"| `{d['table']}` | {d['shared_count']} | {lo} | {jo} |")
    lines.append("")

    # ── Section 2: EFFECT_CONF families ──
    lines.append("## 2. EFFECT_CONF families")
    lines.append("")
    lines.append(
        f"Total `(type, effect_order)` families: **{len(effect_families)}**. "
        "`coverage` is sourced from `roco/generated/audit/effect_families.jsonl` "
        "(this audit does not recompute coverage)."
    )
    lines.append("")
    lines.append(
        "| family_key | type | order | count | param slots | consumers (skill/ability) | coverage | editor_name samples |"
    )
    lines.append("|---|---:|---:|---:|---|---:|---|---|")
    for f in effect_families:
        slots = _fmt_dict_inline(f["param_shape"]["slot_count"])
        samples = ", ".join(f["editor_name_samples"][:3])
        if len(f["editor_name_samples"]) > 3:
            samples += f", … (+{len(f['editor_name_samples']) - 3})"
        lines.append(
            f"| `{f['family_key']}` | {f['type']} | {f['effect_order']} | "
            f"{f['count']} | {slots} | "
            f"{f['consumer_skills']}/{f['consumer_abilities']} | "
            f"`{f['current_coverage_status']}` | {samples} |"
        )
    lines.append("")

    # ── Section 3: BUFFBASE_CONF families ──
    lines.append("## 3. BUFFBASE_CONF families")
    lines.append("")
    lines.append(
        f"Total `buffbase_order` families: **{len(buffbase_fams)}**.  "
        "`buffbase_order rule` is the engine-owned `handles_buff` axis "
        "resolved through `Enum.BuffType`; `prefix rule` is the "
        "mixed-prefix axis kept only for the 3 prefixes whose "
        "buffbase_order distribution is not 100% concentrated."
    )
    lines.append("")
    lines.append(
        "| order | count | param slots | trigger_types | buffbase_order rule | prefix rule (legacy) | refs | editor_name samples |"
    )
    lines.append("|---:|---:|---|---|---|---|---:|---|")
    for b in buffbase_fams:
        slots = _fmt_dict_inline(b["param_slot_count"])
        tt = _fmt_dict_inline(b["trigger_types"])
        order_rule = b["covering_buffbase_order_rule"]
        if order_rule:
            order_rule_str = f"`{order_rule['handler']}`"
            if order_rule.get("alias"):
                order_rule_str += f" ({order_rule['alias']})"
        else:
            order_rule_str = "—"
        pfx_rule = b["covering_prefix_rule"]
        if pfx_rule:
            pfx_rule_str = f"`{pfx_rule['prefix']}`→`{pfx_rule['handler']}` ({pfx_rule['share']})"
        else:
            pfx_rule_str = "—"
        samples = ", ".join(b["editor_name_samples"][:3])
        lines.append(
            f"| **{b['buffbase_order']}** | {b['count']} | {slots} | "
            f"{tt} | {order_rule_str} | {pfx_rule_str} | "
            f"{b['referencing_buff_ids_count']} | {samples} |"
        )
    lines.append("")

    # ── Section 4: rule debt ──
    lines.append("## 4. Rule debt")
    lines.append("")
    lines.append(
        "Migration candidates per rule file.  An exact rule is a "
        "candidate when ≥3 rules share the same "
        "`(EFFECT_CONF.effect_order, handler)` — that cluster can "
        "collapse into one family decoder.  A prefix rule is a "
        "candidate when its dominant `buffbase_order` reaches 100% "
        "concentration."
    )
    lines.append("")

    lines.append("### 4a. Exact compiler semantic clusters")
    lines.append("")
    by_cluster: defaultdict[tuple[int, str], list[dict]] = defaultdict(list)
    candidate_count = 0
    for r in exact_debt:
        if r["migration_candidate"]:
            by_cluster[(r["effect_order"], r["handler"])].append(r)
            candidate_count += 1
    if not by_cluster:
        lines.append("_No exact-rule cluster reaches ≥3 rules._")
    else:
        lines.append("| effect_order | handler | rule count | sample editor_names |")
        lines.append("|---:|---|---:|---|")
        for (order, handler), rows in sorted(
            by_cluster.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ):
            sample_names = sorted({
                r["pak_editor_name"] for r in rows if r["pak_editor_name"]
            })[:3]
            lines.append(
                f"| {order} | `{handler}` | **{len(rows)}** | "
                f"{', '.join(sample_names)} |"
            )
    remaining = len(exact_debt) - candidate_count
    lines.append("")
    lines.append(
        f"_{candidate_count} of {len(exact_debt)} exact rules in migration "
        f"clusters; {remaining} are singletons or sparse._"
    )
    lines.append("")

    lines.append("### 4b. Engine prefix-axis rekey candidates")
    lines.append("")
    lines.append(
        "Per prefix: the dominant `buffbase_order` (the schema axis "
        "underlying the prefix), concentration (% of base_ids with "
        "that prefix that share the dominant order), and whether the "
        "structural identity `prefix - 2000 == buffbase_order` holds."
    )
    lines.append("")
    lines.append(
        "| prefix | handler | alias | dominant order | concentration | "
        "identity? | clean rewrite? |"
    )
    lines.append("|---:|---|---|---:|---:|:---:|:---:|")
    for r in prefix_debt:
        order = r["dominant_buffbase_order"]
        order_str = str(order) if order is not None else "—"
        ident = "✓" if r["implied_identity"] else "—"
        clean = "✓" if r["clean_rewrite"] else "—"
        alias = r["alias"] or ""
        lines.append(
            f"| {r['prefix']} | `{r['handler']}` | {alias} | {order_str} | "
            f"{r['concentration'] * 100:.1f}% | {ident} | {clean} |"
        )
    clean_count = sum(1 for r in prefix_debt if r["clean_rewrite"])
    identity_count = sum(1 for r in prefix_debt if r["implied_identity"])
    lines.append("")
    lines.append(
        f"_{clean_count} of {len(prefix_debt)} prefix rules are clean "
        f"rewrites (100% concentration); {identity_count} satisfy the "
        "`prefix - 2000 == buffbase_order` identity._"
    )

    return "\n".join(lines) + "\n"


# ── orchestration ─────────────────────────────────────────────────


def build_audit() -> str:
    """Run the full mining pipeline and return the rendered markdown."""
    drift = detect_schema_drift()

    effect_conf = _load_pak_table(PAK_BIN / "EFFECT_CONF.json")
    buffbase_conf = _load_pak_table(PAK_BIN / "BUFFBASE_CONF.json")
    buff_conf = _load_pak_table(PAK_BIN / "BUFF_CONF.json")

    skills = _load_canonical("skills.jsonl")
    abilities = _load_canonical("abilities.jsonl")
    skill_users, ability_users = _build_consumer_counts(skills, abilities)
    catalog = _load_effect_families()

    eff_fams = effect_conf_families(
        effect_conf, skill_users, ability_users, catalog,
    )
    prefix_rules, _overrides = _load_prefix_rules()
    buffbase_order_rules = _load_buffbase_order_rules()
    bb_fams = buffbase_families(
        buffbase_conf, buff_conf, prefix_rules, buffbase_order_rules,
    )

    exact_rules = _load_exact_rules()
    exact_debt = exact_rule_debt(exact_rules, effect_conf)
    prefix_debt = prefix_rule_debt(prefix_rules, buffbase_conf)

    return render_markdown(drift, eff_fams, bb_fams, exact_debt, prefix_debt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if on-disk pak_schema_audit.md differs from a fresh build",
    )
    args = parser.parse_args(argv)

    fresh = build_audit()

    if args.check:
        if not AUDIT_MD.exists():
            sys.stderr.write(f"missing: {AUDIT_MD}\n")
            return 1
        on_disk = AUDIT_MD.read_text(encoding="utf-8")
        if on_disk != fresh:
            sys.stderr.write(
                f"stale: {AUDIT_MD}\n"
                "re-run: uv run python -m roco.compiler_v2.pak_schema_audit\n"
            )
            return 1
        return 0

    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_MD.write_text(fresh, encoding="utf-8")
    print(f"pak_schema_audit.md -> {AUDIT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
