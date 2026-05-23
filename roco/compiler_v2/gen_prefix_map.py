"""Generate compiler artifacts with the replacement compiler_v2 pipeline."""

from __future__ import annotations

from roco.compiler_v2.artifacts import write_all


def main() -> None:
    stats = write_all()
    print(f"compiler_v2 source_hash: {stats['source_hash']}")
    print(f"static pak/lua snapshot -> {stats['static_paths']['manifest']}")
    print(f"handler_indices.py: {stats['handler_count']} constants")
    prefix_stats = stats["prefix_stats"]
    print(
        "prefix_handler_map.json: "
        f"{prefix_stats['base_ids_via_order']} base_ids via buffbase_order + "
        f"{prefix_stats['prefixes_in_legacy_map']} mixed prefixes "
        f"({len(prefix_stats['unmapped_prefixes'])} unmapped of "
        f"{prefix_stats['total_prefixes']} seen)"
    )
    print(f"battle_globals.py: {stats['battle_global_num_count']} numeric keys")
    print(f"skill_dam_types.py: {stats['skill_dam_type_count']} element adapters")
    print(f"mark_groups.py: {stats['mark_group_count']} cover groups")
    print(f"pak_ops.py: {stats['pak_op_count']} prefixes")
    print(f"type_chart.py: {stats['type_chart_size']}x{stats['type_chart_size']} BPS table")
    print(f"weather_decoders.py: {stats['weather_count']} weather effects")
    print(f"counter_skill_table.py: {stats['counter_count']} counter response skills")
    print(f"buff_immunity_table.py: {stats['immunity_count']} immunity buffs")
    print(f"buffbase_params.py: {stats['buffbase_count']} base ids")
    print(f"natures.py: {stats['nature_count']} player natures")
    adapters = stats["canonical_adapter_counts"]
    print(
        "canonical_adapters.py: "
        f"{adapters['move_category_count']} move category adapters + "
        f"{adapters['mark_def_count']} mark defs"
    )


if __name__ == "__main__":
    main()
