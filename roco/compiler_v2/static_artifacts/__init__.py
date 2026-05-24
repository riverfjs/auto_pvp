from __future__ import annotations

from .battle_events import write_battle_events
from .bloodline_magic import build_bloodline_magic_tables, write_bloodline_magic
from .buffbase import BUFFBASE_PARAMS_PATH, _normalize_slot, build_buffbase_tables, write_buffbase_params
from .canonical_adapters import build_canonical_adapters, write_canonical_adapters
from .common import (
    BATTLE_GLOBALS_PATH,
    BATTLE_EVENTS_PATH,
    BLOODLINE_MAGIC_PATH,
    BUFFBASE_PARAMS_PATH,
    BUFF_IMMUNITY_PATH,
    CANONICAL_ADAPTERS_PATH,
    COUNTER_SKILL_TABLE_PATH,
    MARK_GROUPS_PATH,
    NATURES_PATH,
    PAK_OPS_PATH,
    PRIMITIVE_MAP_PATH,
    SKILL_DAM_TYPES_PATH,
    TYPE_CHART_PATH,
    WEATHER_DECODERS_PATH,
    WEATHER_TABLE_PATH,
)
from .core import write_battle_globals, write_pak_ops, write_skill_dam_types, write_type_chart
from .counter_skill import write_counter_skill_table
from .immunity import write_buff_immunity_table
from .marks import MarkIdx, mark_note_by_idx, mark_note_to_primitive, write_mark_groups
from .natures import build_nature_tables, write_natures
from .orchestrator import write_all
from .prefix_map import write_primitive_map
from .weather import build_weather_tables, write_weather_decoders, write_weather_table

__all__ = [
    "BATTLE_GLOBALS_PATH",
    "BATTLE_EVENTS_PATH",
    "BLOODLINE_MAGIC_PATH",
    "BUFFBASE_PARAMS_PATH",
    "BUFF_IMMUNITY_PATH",
    "CANONICAL_ADAPTERS_PATH",
    "COUNTER_SKILL_TABLE_PATH",
    "MARK_GROUPS_PATH",
    "NATURES_PATH",
    "PAK_OPS_PATH",
    "PRIMITIVE_MAP_PATH",
    "SKILL_DAM_TYPES_PATH",
    "TYPE_CHART_PATH",
    "WEATHER_DECODERS_PATH",
    "WEATHER_TABLE_PATH",
    "MarkIdx",
    "_normalize_slot",
    "build_bloodline_magic_tables",
    "build_buffbase_tables",
    "build_canonical_adapters",
    "build_nature_tables",
    "build_weather_tables",
    "mark_note_by_idx",
    "mark_note_to_primitive",
    "write_all",
    "write_battle_events",
    "write_battle_globals",
    "write_bloodline_magic",
    "write_buff_immunity_table",
    "write_buffbase_params",
    "write_canonical_adapters",
    "write_counter_skill_table",
    "write_mark_groups",
    "write_natures",
    "write_pak_ops",
    "write_primitive_map",
    "write_skill_dam_types",
    "write_type_chart",
    "write_weather_decoders",
    "write_weather_table",
]
