"""Audit BinData coverage for generated battle/static data.

This report is intentionally mechanical: enumerate every extracted pak
``BinData`` table, scan project code for table references, and highlight
combat-looking tables that are not yet part of a generated path.  It also
flags kernel constants that still live as source assignments instead of
coming from pak-derived generated modules.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

from roco.compiler_v2.sources import DEFAULT_PAK_DATA_DIR


ROOT = Path(__file__).resolve().parents[2]
PAK_BIN = DEFAULT_PAK_DATA_DIR / "BinData"
AUDIT_JSON = ROOT / "roco" / "generated" / "audit" / "bindata_coverage.json"

CODE_ROOTS = (
    ROOT / "roco",
)
CODE_SUFFIXES = {".py"}
SCAN_EXCLUDE_NAMES = {
    "__pycache__",
    ".pytest_cache",
}
SCAN_EXCLUDE_FILES = {
    Path(__file__).resolve(),
}

COMBAT_TABLE_NAME_RE = re.compile(
    r"(SKILL|EFFECT|BUFF|BATTLE|PVP|PET|WEATHER|STATUS|MAGIC|COMBAT|"
    r"BLOOD|TYPE|WEAKNESS|POWER|ATTRIBUTE|MARK|NATURE|PREATTACK|UNCOMMAND)"
)
COMBAT_FIELD_RE = re.compile(
    r"(skill|effect|buff|battle|pet|weather|status|magic|blood|damage|"
    r"target|energy|power|hp|attack|defence|speed|round|type|mark)",
    re.IGNORECASE,
)
UI_TABLE_RE = re.compile(
    r"(UI|RES_|ANIM|AUDIO|FASHION|MALL|SHOP|ACTIVITY|TASK|GUIDE|"
    r"PHOTO|CAMERA|MUSIC|DIALOGUE|MOVIE|NPC_|WORLD_MAP|TELEPORT|"
    r"HEADWEAR|RIDE|HOME|FURNITURE|LOADING|NOTICE|MAIL|BAG_|CARD_|"
    r"CHAT|BUTTON|PLATFORM|DEVICE|BENCHMARK|LLM_|MAP_)"
)

CORE_TABLES = {
    "SKILL_CONF",
    "EFFECT_CONF",
    "BUFF_CONF",
    "BUFFBASE_CONF",
    "TYPE_DICTIONARY",
    "BATTLE_GLOBAL_CONFIG",
    "PETBASE_CONF",
    "DESC_NOTE_CONF",
    "NATURE_CONF",
    "ATTRIBUTE_CONF",
    "WEATHER_CONF",
    "PLAYER_MAGIC_CONF",
    "PET_BLOOD_CONF",
    "BAG_ITEM_CONF",
}

MANUAL_SEMANTIC_BINDINGS = (
    {
        "file": "roco/compiler_v2/buff_immunity_decoders.py",
        "symbol": "IMMUNITY_SPECS",
        "reason": "manual immunity tag/bit/keyword binding over BUFF_CONF.desc",
    },
    {
        "file": "roco/compiler_v2/static_artifacts/marks.py",
        "symbol": "MARK_NOTE_BY_IDX",
        "reason": "manual canonical mark note-id/name/index binding over DESC_NOTE_CONF",
    },
    {
        "file": "roco/common/enums.py",
        "symbol": "Element/SkillCategory/StatusType/WeatherType",
        "reason": "runtime enums should be generated or checked against Lua/BinData enums",
    },
)

ALLOWED_POLICY_CONSTANTS = {
    "BPS",
    "DEFAULT_MAX_TURNS",
}

GENERATED_STATIC_SYMBOLS = {
    "BATTLE_GLOBAL_NUMS",
    "PLAYER_MAGIC_LEADER_TRANSFORM_ID",
    "PLAYER_MAGIC_WILLPOWER_ID",
    "PLAYER_MAGICS_BY_ID",
    "PAK_BLOODLINE_LEADER",
    "PAK_BLOODLINE_POLLUTANT",
    "WILLPOWER_BASE_POWER",
    "GENERATED_WILLPOWER_COUNTER_STATUS_BPS",
}


def build_audit() -> dict[str, Any]:
    tables = _table_records()
    refs = _code_references({row["table"] for row in tables})
    for row in tables:
        table = row["table"]
        row["code_refs"] = refs.get(table, [])
        row["referenced_by_code"] = bool(row["code_refs"])
        row["coverage"] = _coverage(row)

    combat_candidates = [row for row in tables if row["combat_candidate"]]
    unreferenced_combat = [
        row["table"]
        for row in combat_candidates
        if not row["referenced_by_code"] and row["category"] != "ui_or_content"
    ]
    unreferenced_core = [
        row["table"]
        for row in tables
        if row["category"] == "core_battle" and not row["referenced_by_code"]
    ]
    referenced_combat = [
        row["table"]
        for row in combat_candidates
        if row["referenced_by_code"]
    ]
    constants = _manual_kernel_constants()
    audit = {
        "summary": {
            "bindata_table_count": len(tables),
            "combat_candidate_count": len(combat_candidates),
            "referenced_combat_table_count": len(referenced_combat),
            "unreferenced_core_table_count": len(unreferenced_core),
            "unreferenced_combat_table_count": len(unreferenced_combat),
            "manual_kernel_constant_count": len(constants),
            "manual_semantic_binding_count": len(MANUAL_SEMANTIC_BINDINGS),
        },
        "core_unreferenced_tables": unreferenced_core,
        "combat_unreferenced_tables": unreferenced_combat,
        "manual_kernel_constants": constants,
        "manual_semantic_bindings": list(MANUAL_SEMANTIC_BINDINGS),
        "tables": tables,
    }
    return audit


def render_json(audit: dict[str, Any]) -> str:
    return json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _table_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(PAK_BIN.glob("*.json")):
        table = path.stem
        count, fields = _table_shape(path)
        category = _category(table, fields)
        rows.append({
            "table": table,
            "path": path.relative_to(ROOT).as_posix(),
            "row_count": count,
            "fields": fields,
            "field_count": len(fields),
            "category": category,
            "combat_candidate": category in {"core_battle", "battle_candidate", "combat_content"},
        })
    return rows


def _table_shape(path: Path) -> tuple[int, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    table = data.get("RocoDataRows", data) if isinstance(data, dict) else data
    values: list[Any]
    if isinstance(table, dict):
        values = list(table.values())
    elif isinstance(table, list):
        values = table
    else:
        return 0, []
    fields: set[str] = set()
    for rec in values[:64]:
        if isinstance(rec, dict):
            fields.update(str(k) for k in rec)
    return len(values), sorted(fields)


def _category(table: str, fields: list[str]) -> str:
    if table in CORE_TABLES:
        return "core_battle"
    if UI_TABLE_RE.search(table):
        return "ui_or_content"
    if COMBAT_TABLE_NAME_RE.search(table):
        return "battle_candidate"
    if any(COMBAT_FIELD_RE.search(field) for field in fields):
        return "combat_content"
    return "non_battle"


def _coverage(row: dict[str, Any]) -> str:
    if row["referenced_by_code"]:
        if any(ref.startswith("roco/compiler_v2/") or ref.startswith("roco/data/") for ref in row["code_refs"]):
            return "generator_or_importer_referenced"
        if any(ref.startswith("roco/generated/") for ref in row["code_refs"]):
            return "generated_output_mentions"
        return "referenced"
    if row["combat_candidate"]:
        return "combat_candidate_unreferenced"
    return "unreferenced"


def _code_references(table_names: set[str]) -> dict[str, list[str]]:
    refs: dict[str, set[str]] = {name: set() for name in table_names}
    patterns = {
        name: re.compile(rf"\b{re.escape(name)}(?:\.json)?\b")
        for name in table_names
    }
    for root in CODE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.resolve() in SCAN_EXCLUDE_FILES:
                continue
            if any(part in SCAN_EXCLUDE_NAMES for part in path.parts):
                continue
            if path.suffix not in CODE_SUFFIXES:
                continue
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8", errors="ignore")
            for table, pattern in patterns.items():
                if pattern.search(text):
                    refs[table].add(rel)
    return {table: sorted(paths) for table, paths in refs.items() if paths}


def _manual_kernel_constants() -> list[dict[str, Any]]:
    path = ROOT / "roco" / "common" / "constants.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.isupper() or name in ALLOWED_POLICY_CONSTANTS:
            continue
        if _is_generated_static_alias(node.value):
            continue
        out.append({
            "file": path.relative_to(ROOT).as_posix(),
            "line": node.lineno,
            "name": name,
            "value": ast.unparse(node.value),
        })
    return out


def _is_generated_static_alias(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Name) and child.id in GENERATED_STATIC_SYMBOLS
        for child in ast.walk(node)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the generated audit differs from a fresh build",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=AUDIT_JSON,
        help="output JSON path",
    )
    args = parser.parse_args(argv)

    fresh = render_json(build_audit())
    if args.check:
        if not args.out.exists():
            print(f"missing audit: {args.out}")
            return 1
        current = args.out.read_text(encoding="utf-8")
        if current != fresh:
            print(
                f"{args.out} is out of date; "
                "re-run: uv run python -m roco.compiler_v2.bindata_coverage_audit"
            )
            return 1
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(fresh, encoding="utf-8")
    print(f"bindata_coverage.json -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
