from __future__ import annotations

from .battle_events import write_battle_events
from .bloodline_magic import build_bloodline_magic_tables, write_bloodline_magic
from .buffs import build_buff_tables, write_buff_defs
from .buffbase import BUFFBASE_PARAMS_PATH, _normalize_slot, build_buffbase_tables, write_buffbase_params
from .canonical_adapters import build_canonical_adapters, write_canonical_adapters
from .common import (
    BATTLE_GLOBALS_PATH,
    BATTLE_EVENTS_PATH,
    BLOODLINE_MAGIC_PATH,
    BUFF_DEFS_PATH,
    BUFFBASE_PARAMS_PATH,
    BUFF_IMMUNITY_PATH,
    CANONICAL_ADAPTERS_PATH,
    COUNTER_SKILL_TABLE_PATH,
    MARK_GROUPS_PATH,
    NATURES_PATH,
    PAK_GEN_DIR,
    PAK_INIT_PATH,
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
from .marks import MarkIdx, mark_desc_by_idx, mark_desc_to_idx, write_mark_groups
from .natures import build_nature_tables, write_natures
from .orchestrator import write_all
from .prefix_map import write_primitive_map
from .weather import build_weather_tables, write_weather_decoders, write_weather_table

__all__ = [
    "BATTLE_GLOBALS_PATH",
    "BATTLE_EVENTS_PATH",
    "BLOODLINE_MAGIC_PATH",
    "BUFF_DEFS_PATH",
    "BUFFBASE_PARAMS_PATH",
    "BUFF_IMMUNITY_PATH",
    "CANONICAL_ADAPTERS_PATH",
    "COUNTER_SKILL_TABLE_PATH",
    "MARK_GROUPS_PATH",
    "NATURES_PATH",
    "PAK_GEN_DIR",
    "PAK_INIT_PATH",
    "PAK_OPS_PATH",
    "PRIMITIVE_MAP_PATH",
    "SKILL_DAM_TYPES_PATH",
    "TYPE_CHART_PATH",
    "WEATHER_DECODERS_PATH",
    "WEATHER_TABLE_PATH",
    "MarkIdx",
    "_normalize_slot",
    "build_bloodline_magic_tables",
    "build_buff_tables",
    "build_buffbase_tables",
    "build_canonical_adapters",
    "build_nature_tables",
    "build_weather_tables",
    "mark_desc_by_idx",
    "mark_desc_to_idx",
    "write_all",
    "write_battle_events",
    "write_battle_globals",
    "write_bloodline_magic",
    "write_buff_immunity_table",
    "write_buff_defs",
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
