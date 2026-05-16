"""Weather system for Roco Kingdom PVP simulation.

Supported weathers: rain (水系+50%), sandstorm (非地/钢/机械受1/16伤害),
snow (每回合累积冻伤).
"""

WEATHER_DAMAGE_MULT: dict[str, dict[str, float]] = {
    "rain": {"水": 1.5},
    "sandstorm": {},
    "snow": {},
}

# Sandstorm: types immune to end-of-turn chip damage
SANDSTORM_IMMUNE = frozenset({"地", "岩", "钢", "机械"})

# Snow: frostbite per turn = max_hp // 12
SNOW_FROSTBITE_FRACTION = 12

# Weather end-of-turn chip: 1/16 of max HP
WEATHER_CHIP_FRACTION = 16


def weather_damage_mult(move_element: str, weather: str | None) -> float:
    """Get the damage multiplier from weather for a move element."""
    if not weather:
        return 1.0
    return WEATHER_DAMAGE_MULT.get(weather, {}).get(move_element, 1.0)


def is_sandstorm_immune(element: str) -> bool:
    return element in SANDSTORM_IMMUNE


def sandstorm_chip_damage(max_hp: int) -> int:
    """Sandstorm end-of-turn damage: floor(max_hp / 16)."""
    return max_hp // WEATHER_CHIP_FRACTION


def snow_frostbite_damage(max_hp: int) -> int:
    """Snow end-of-turn frostbite accumulation: floor(max_hp / 12)."""
    return max_hp // SNOW_FROSTBITE_FRACTION
