"""Codegen for ``roco/generated/counter_skill_table.py``.

The pak counter-trigger family (effect_ids 1031xxx) carries a 70xxxxx
response skill_id in ``effect_param[0]``.  When ``op_install_counter``
arms a side's ``counter_skill_id``, the kernel reads this table to
resolve the response skill's combat stats (power, element, category,
damage type code, priority).  Built directly from SKILL_CONF so adding
a new "应对！X" pak skill only requires a parse_pak re-run.

The ``_PAK_SKILL_DAM_TYPE_TO_ELEMENT`` table below is a **schema adapter**
(pak ``skill_dam_type`` → project ``Element`` enum value), not battle
rule data.  Leaving it in Python is intentional — see
``_docs/phase4_dataization_boundaries.md``.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
COUNTER_SKILL_TABLE_PATH = GEN_DIR / "counter_skill_table.py"


# Pak ``skill_dam_type`` → kernel ``Element`` value.  Same mapping pak uses
# everywhere; collapsing 7+8 → GROUND matches the canonical name table in
# ``parse_pak.SKILL_DAM_TYPE_TO_ELEMENT``.  Pak ``damage_type`` 2/3 → kernel
# ``SkillCategory`` PHYSICAL/MAGICAL; pak ``Skill_Type`` 2/3 distinguish
# STATUS/DEFENSE for non-attack response skills (still get a kernel category
# code so ``mechanics`` can route them through ``damage()`` if needed).
_PAK_SKILL_DAM_TYPE_TO_ELEMENT = {
    2: 0,   # 普通 NORMAL
    3: 1,   # 草 GRASS
    4: 2,   # 火 FIRE
    5: 3,   # 水 WATER
    6: 4,   # 光 LIGHT
    7: 5,   # 地 GROUND
    8: 5,   # 地 GROUND (pak alias)
    9: 6,   # 冰 ICE
    10: 7,  # 龙 DRAGON
    11: 8,  # 电 ELECTRIC
    12: 9,  # 毒 POISON
    13: 10, # 虫 BUG
    14: 11, # 武 FIGHTING
    15: 12, # 翼 FLYING
    16: 13, # 萌 CUTE
    17: 14, # 幽 GHOST
    18: 15, # 恶 DARK
    19: 16, # 机械 MECHANICAL
    20: 17, # 幻 ILLUSION
}


def load_counter_skill_table(
    pak_data_dir: Path = PAK_DATA,
) -> list[tuple[int, int, int, int, int, int, str]]:
    """Return ``[(csid, power, element, category, dam_type, priority, name), ...]``."""
    effect_path = pak_data_dir / "EFFECT_CONF.json"
    skill_path = pak_data_dir / "SKILL_CONF.json"
    effect_rows = json.loads(effect_path.read_text(encoding="utf-8")).get("RocoDataRows", {})
    skill_rows = json.loads(skill_path.read_text(encoding="utf-8")).get("RocoDataRows", {})

    counter_skill_ids: set[int] = set()
    for eid_str, rec in effect_rows.items():
        eid = int(eid_str)
        if not (1031000 <= eid <= 1031999):
            continue
        params = rec.get("effect_param") or rec.get("params") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        csid = int(inner[0])
        if 7000000 <= csid < 8000000:
            counter_skill_ids.add(csid)

    table: list[tuple[int, int, int, int, int, int, str]] = []
    for csid in sorted(counter_skill_ids):
        row = skill_rows.get(str(csid))
        if row is None:
            continue  # missing in pak; defender just won't counter
        dam_para = row.get("dam_para") or [0]
        power = int(dam_para[0] if isinstance(dam_para, list) and dam_para else 0)
        skill_dam_type = int(row.get("skill_dam_type") or 0)
        element = _PAK_SKILL_DAM_TYPE_TO_ELEMENT.get(skill_dam_type, 0)
        pak_damage_type = int(row.get("damage_type") or 0)
        pak_skill_type = int(row.get("Skill_Type") or 0)
        # Kernel category: physical=1 magical=2 defense=3 status=4.  Map
        # pak damage_type=2 → physical, =3 → magical; for non-attack
        # response skills fall back to Skill_Type=3 → defense, =2 → status.
        if pak_damage_type == 2:
            category = 1
        elif pak_damage_type == 3:
            category = 2
        elif pak_skill_type == 3:
            category = 3
        elif pak_skill_type == 2:
            category = 4
        else:
            category = 0
        priority = int(row.get("skill_priority") or 0)
        name = str(row.get("name") or "")
        table.append((csid, power, element, category, pak_damage_type, priority, name))
    return table


def render(table: list[tuple[int, int, int, int, int, int, str]]) -> str:
    lines = [
        "# Auto-generated from SKILL_CONF.json + EFFECT_CONF.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "# counter_skill_id -> (power, element, category, dam_type, priority)",
        "COUNTER_SKILL_TABLE: dict[int, tuple[int, int, int, int, int]] = {",
    ]
    for csid, power, element, category, dam_type, priority, name in table:
        lines.append(f"    {csid}: ({power}, {element}, {category}, {dam_type}, {priority}),  # {name}")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_counter_skill_table(pak_data_dir: Path = PAK_DATA) -> int:
    table = load_counter_skill_table(pak_data_dir)
    COUNTER_SKILL_TABLE_PATH.write_text(render(table), encoding="utf-8")
    return len(table)
