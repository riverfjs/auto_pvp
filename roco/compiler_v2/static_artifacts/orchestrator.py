from __future__ import annotations

from typing import Any

from roco.compiler_v2.build import build_static_bundle
from roco.compiler_v2.emit import write_static_files

from .battle_events import write_battle_events
from .bloodline_magic import write_bloodline_magic
from .buffs import write_buff_defs
from .buffbase import write_buffbase_params
from .canonical_adapters import write_canonical_adapters
from .common import GEN_DIR, INIT_PATH, STATIC_DIR
from .core import write_battle_globals, write_pak_ops, write_skill_dam_types, write_type_chart
from .counter_skill import write_counter_skill_table
from .effects import write_effect_params
from .immunity import write_buff_immunity_table
from .marks import write_mark_groups
from .natures import write_natures
from .prefix_map import write_primitive_map
from .weather import write_weather_decoders, write_weather_table


def write_all() -> dict[str, Any]:
    """Write every generated artifact and return build stats."""
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    INIT_PATH.write_text('"""Auto-generated package for compiler_v2 artifacts."""\n', encoding="utf-8")
    bundle = build_static_bundle()
    static_paths = write_static_files(bundle, STATIC_DIR)

    battle_event_count = write_battle_events(bundle)
    primitive_result = write_primitive_map(bundle)
    battle_global_count = write_battle_globals(bundle)
    skill_dam_type_count = write_skill_dam_types(bundle)
    mark_groups = write_mark_groups(primitive_result)
    pak_op_count = write_pak_ops(bundle, primitive_result["prefix_aliases"])
    type_chart_size = write_type_chart(bundle)
    weather_table_count = write_weather_table(bundle)
    weather_count = write_weather_decoders(bundle)
    counter_count = write_counter_skill_table(bundle)
    immunity_count = write_buff_immunity_table()
    bloodline_magic_counts = write_bloodline_magic(bundle)
    buffbase_count = write_buffbase_params()
    buff_count = write_buff_defs()
    effect_count = write_effect_params()
    nature_count = write_natures()
    canonical_adapter_counts = write_canonical_adapters()

    return {
        "source_hash": bundle.source_hash,
        "static_paths": static_paths,
        "battle_event_count": battle_event_count,
        "primitive_stats": primitive_result["stats"],
        "battle_global_num_count": battle_global_count,
        "skill_dam_type_count": skill_dam_type_count,
        "mark_group_count": len(mark_groups),
        "pak_op_count": pak_op_count,
        "type_chart_size": type_chart_size,
        "weather_table_count": weather_table_count,
        "weather_count": weather_count,
        "counter_count": counter_count,
        "immunity_count": immunity_count,
        "bloodline_magic_counts": bloodline_magic_counts,
        "buffbase_count": buffbase_count,
        "buff_count": buff_count,
        "effect_count": effect_count,
        "nature_count": nature_count,
        "canonical_adapter_counts": canonical_adapter_counts,
    }
