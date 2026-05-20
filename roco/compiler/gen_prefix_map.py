"""Auto-generate every ``roco/generated/`` codegen artifact.

Thin orchestrator: each codegen module under ``roco/compiler/codegen/``
owns its own load/derive/render/write pipeline.  This file's job is to
call them in dependency order and surface the same per-artifact summary
lines older callers expect.

Outputs (all under ``roco/generated/``):

* ``handler_indices.py``, ``handler_order.py``, ``handler_table.py``,
  ``handler_registry.json`` — ``codegen/handlers.py``
* ``prefix_handler_map.json`` — ``codegen/prefixes.py``
* ``pak_rules.py`` — ``codegen/pak_rules.py``
* ``mark_groups.py`` — ``codegen/marks.py``
* ``pak_ops.py`` — ``codegen/pak_ops.py``
* ``type_chart.py`` — ``codegen/type_chart.py``
  (depends on ``pak_rules.py`` having been written first)
* ``weather_decoders.py`` — ``codegen/weather.py``
* ``counter_skill_table.py`` — ``codegen/counter_skills.py``
* ``buff_immunity_table.py`` — ``codegen/buff_immunity_codegen.py``

Run at build time::

    uv run python -m roco.compiler.gen_prefix_map
"""

from __future__ import annotations

import sys

from roco.compiler.codegen import (
    counter_skills,
    handlers,
    marks,
    pak_ops,
    pak_rules,
    prefixes,
    type_chart,
    weather,
)
from roco.compiler.codegen.buff_immunity_codegen import write_buff_immunity_table


def main() -> None:
    h = handlers.write_handler_artifacts()
    print(f"handler_indices.py: {len(h)} constants -> {handlers.INDICES_PATH}")
    print(f"handler_table.py:   {len(h)} handlers   -> {handlers.TABLE_PATH}")

    result = prefixes.write_prefix_handler_map(h)
    stats = result["stats"]
    print(f"prefix_handler_map.json: {stats['mapped_prefixes']} mapped, "
          f"{len(stats['unmapped_prefixes'])} unmapped (of {stats['total_prefixes']} seen) "
          f"-> {prefixes.PREFIX_MAP_PATH}")
    if stats["unmapped_prefixes"]:
        print(f"  unmapped: {stats['unmapped_prefixes']}", file=sys.stderr)

    rules = pak_rules.write_pak_rules_table()
    print(f"pak_rules.py: {len(rules)} constants -> {pak_rules.PAK_RULES_PATH}")

    groups = marks.write_mark_groups(h, result)
    print(f"mark_groups.py: {len(groups)} cover groups -> {marks.MARK_GROUPS_PATH}")

    pak_op_count = pak_ops.write_pak_ops_table()
    print(f"pak_ops.py: {pak_op_count} prefixes -> {pak_ops.PAK_OPS_PATH}")

    chart_size = type_chart.write_type_chart()
    print(f"type_chart.py: {chart_size}x{chart_size} BPS table -> {type_chart.TYPE_CHART_PATH}")

    weather_count = weather.write_weather_decoders()
    print(f"weather_decoders.py: {weather_count} pak weather effects -> {weather.WEATHER_DECODERS_PATH}")

    counter_count = counter_skills.write_counter_skill_table()
    print(f"counter_skill_table.py: {counter_count} counter response skills "
          f"-> {counter_skills.COUNTER_SKILL_TABLE_PATH}")

    immunity_path = write_buff_immunity_table()
    print(f"buff_immunity_table.py -> {immunity_path}")


if __name__ == "__main__":
    main()
