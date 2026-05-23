"""In-memory model for the experimental static compiler."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StaticBundle:
    source_hash: str
    source_files: tuple[Path, ...]
    lua_enums: dict[str, dict[str, int]]
    lua_enum_references: dict[str, dict[str, int]]
    battle_global_nums: dict[str, int]
    battle_global_lists: dict[str, tuple[int, ...]]
    battle_global_strings: dict[str, str]
    skill_dam_type_names: dict[int, str]
    skill_dam_type_to_element: dict[int, int]
    skill_dam_type_to_element_name: dict[int, str]
    skill_dam_type_unmapped: dict[int, str]
    effect_order_names: dict[int, str]
    effect_order_counts: dict[int, int]
    buffbase_order_names: dict[int, str]
    buffbase_order_counts: dict[int, int]
    buff_base_to_order: dict[int, int]
    buff_id_to_base_ids: dict[int, tuple[int, ...]]
