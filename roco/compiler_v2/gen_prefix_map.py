"""Generate compiler artifacts with the replacement compiler_v2 pipeline."""

from __future__ import annotations

from roco.compiler_v2.static_artifacts import write_all


def main() -> None:
    stats = write_all()
    print(f"compiler_v2 source_hash: {stats['source_hash']}")
    print(f"static pak/lua snapshot -> {stats['static_paths']['manifest']}")
    print(f"battle_events.py: {stats['battle_event_count']} BattleEvent constants")
    primitive_stats = stats["primitive_stats"]
    print(
        "primitive_map.json: "
        f"{primitive_stats['base_ids_via_order']} base_ids via buffbase_order + "
        f"{primitive_stats['mixed_prefix_count']} mixed prefixes "
        f"({len(primitive_stats['unmapped_prefixes'])} unmapped of "
        f"{primitive_stats['total_prefixes']} seen)"
    )
    print(f"battle_globals.py: {stats['battle_global_num_count']} numeric keys")
    print(f"skill_dam_types.py: {stats['skill_dam_type_count']} element adapters")
    print(f"mark_groups.py: {stats['mark_group_count']} cover groups")
    print(f"pak_ops.py: {stats['pak_op_count']} prefixes")
    print(f"type_chart.py: {stats['type_chart_size']}x{stats['type_chart_size']} BPS table")
    print(f"weather_table.py: {stats['weather_table_count']} WEATHER_CONF rows")
    print(f"weather_decoders.py: {stats['weather_count']} weather effects")
    print(f"counter_skill_table.py: {stats['counter_count']} counter response skills")
    print(f"buff_immunity_table.py: {stats['immunity_count']} immunity buffs")
    bloodline = stats["bloodline_magic_counts"]
    print(
        "bloodline_magic.py: "
        f"{bloodline['bloodline_count']} bloodlines + "
        f"{bloodline['player_magic_count']} player magics "
        f"({bloodline['supported_magic_count']} engine-supported)"
    )
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
