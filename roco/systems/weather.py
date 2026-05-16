from roco.engine.state import StatusFlag, StatusType
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


# ── Event bus registration ─────────────────────────────────────

def register_weather_handlers(bus: "EventBus") -> None:
    """Register weather effects on the event bus."""
    from roco.engine.events import GameEvent, EventCtx

    def weather_tick(ctx: EventCtx) -> None:
        state = ctx.state
        weather = state.weather
        if not weather:
            return

        # Weather duration
        if state.weather_turns > 0:
            state.weather_turns -= 1
            if state.weather_turns <= 0:
                state.weather = None
                return

        if weather == "sandstorm":
            for pet in state.team_a + state.team_b:
                if pet.is_fainted or is_sandstorm_immune(pet.element_primary):
                    continue
                dmg = sandstorm_chip_damage(pet.max_hp)
                pet.current_hp = max(0, pet.current_hp - dmg)
        elif weather == "snow":
            for pet in state.team_a + state.team_b:
                if pet.is_fainted:
                    continue
                frost = snow_frostbite_damage(pet.max_hp)
                pet.frostbite_damage += frost
                pet.status_flags |= StatusFlag.FREEZE; pet.set_status_count(StatusType.FREEZE,  pet.get_status_count(StatusType.FREEZE) + 2)

    bus.on(GameEvent.TURN_END, weather_tick, priority=250, source="weather")
