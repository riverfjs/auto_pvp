"""Version-checked access to the fixed-kernel hot catalog artifact."""

from __future__ import annotations

EXPECTED_CATALOG_VERSION = 1
EXPECTED_SCHEMA_VERSION = "kernel-v1"
STAT_HP = 1
STAT_ATK_PHYS = 2
STAT_ATK_MAG = 3
STAT_DEF_PHYS = 4
STAT_DEF_MAG = 5
STAT_SPEED = 6
PET_PRIMARY = 7
PET_SECONDARY = 8
PET_ABILITY = 9
SKILL_ELEMENT = 1
SKILL_CATEGORY = 2
SKILL_ENERGY = 3
SKILL_POWER = 4
SKILL_FLAGS = 5
SKILL_HIT_COUNT = 6
SKILL_FLAG_AGILITY = 4194304
SKILL_FLAG_DEVOTION = 16777216
SKILL_FLAG_CHARGE = 2048
ELEMENT_GRASS = 1
ELEMENT_FIRE = 2
ELEMENT_WATER = 3
ELEMENT_LIGHT = 4
ELEMENT_GROUND = 5
ELEMENT_ICE = 6
ELEMENT_BUG = 10
ELEMENT_POISON = 9
ELEMENT_MECHANICAL = 16
ELEMENT_ILLUSION = 17


def validate_catalog(catalog) -> None:
    if catalog.CATALOG_VERSION != EXPECTED_CATALOG_VERSION:
        raise RuntimeError("kernel catalog version mismatch")
    if catalog.SCHEMA_VERSION != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError("kernel catalog schema mismatch")
    if not catalog.SOURCE_HASH:
        raise RuntimeError("kernel catalog source hash is empty")


def load_hot_catalog():
    from roco.engine.generated import catalog_hot

    validate_catalog(catalog_hot)
    return catalog_hot
