from __future__ import annotations

import json
from pathlib import Path
from pprint import pformat
from typing import Any

from roco.compiler_v2.sources import DEFAULT_PAK_DATA_DIR


ROOT = Path(__file__).resolve().parents[3]
GEN_DIR = ROOT / "roco" / "generated"
PAK_DATA = DEFAULT_PAK_DATA_DIR
PAK_BIN = DEFAULT_PAK_DATA_DIR / "BinData"

INIT_PATH = GEN_DIR / "__init__.py"
PRIMITIVE_MAP_PATH = GEN_DIR / "primitive_map.json"
BATTLE_EVENTS_PATH = GEN_DIR / "battle_events.py"
BATTLE_GLOBALS_PATH = GEN_DIR / "battle_globals.py"
PAK_OPS_PATH = GEN_DIR / "pak_ops.py"
SKILL_DAM_TYPES_PATH = GEN_DIR / "skill_dam_types.py"
TYPE_CHART_PATH = GEN_DIR / "type_chart.py"
WEATHER_TABLE_PATH = GEN_DIR / "weather_table.py"
WEATHER_DECODERS_PATH = GEN_DIR / "weather_decoders.py"
COUNTER_SKILL_TABLE_PATH = GEN_DIR / "counter_skill_table.py"
BUFFBASE_PARAMS_PATH = GEN_DIR / "buffbase_params.py"
BUFF_IMMUNITY_PATH = GEN_DIR / "buff_immunity_table.py"
BLOODLINE_MAGIC_PATH = GEN_DIR / "bloodline_magic.py"
MARK_GROUPS_PATH = GEN_DIR / "mark_groups.py"
NATURES_PATH = GEN_DIR / "natures.py"
CANONICAL_ADAPTERS_PATH = GEN_DIR / "canonical_adapters.py"
STATIC_DIR = GEN_DIR / "static"


def _load_json_table(path: Path) -> dict[int | str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("RocoDataRows", data)
    return {_coerce_key(k): v for k, v in rows.items()}

def _coerce_key(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value

def _maybe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _assign(name: str, value: Any) -> str:
    return f"{name} = {pformat(value, width=100, sort_dicts=True)}\n"

def _first_int(raw: Any, default: int = 0) -> int:
    if isinstance(raw, (list, tuple)):
        for value in raw:
            parsed = _maybe_int(value)
            if parsed is not None:
                return parsed
        return default
    parsed = _maybe_int(raw)
    return default if parsed is None else parsed
