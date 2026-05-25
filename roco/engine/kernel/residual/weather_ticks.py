"""End-of-turn weather effects and lifecycle."""

from __future__ import annotations

from roco.common.constants import SANDSTORM_DAMAGE_DENOM, SNOW_FREEZE_STACKS
from roco.common.enums import StatusType, WeatherType
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.core.catalog import STAT_HP
from roco.engine.kernel.effects.damage import sandstorm_immune
from roco.engine.kernel.model.state import (
    KernelState,
    pack_weather,
    replace_pet,
    replace_side,
    side,
    weather_turns,
    weather_type,
    with_status,
)
from roco.generated.catalog import hot


def tick_weather(state: KernelState) -> KernelState:
    """Apply per-weather residuals (sandstorm chip, snow freeze) and decay turns."""
    current = weather_type(state.weather)
    turns = weather_turns(state.weather)
    if current == WeatherType.NONE.value:
        return state
    for side_id in (SIDE_A, SIDE_B):
        side_state = side(state, side_id)
        slot = side_state.active
        pet = side_state.pets[slot]
        if pet.fainted:
            continue
        if current == WeatherType.SANDSTORM.value and not sandstorm_immune(pet):
            damage = hot.PETS[pet.pet_id][STAT_HP] // SANDSTORM_DAMAGE_DENOM
            pet = pet._replace(current_hp=max(1, pet.current_hp - damage))
        elif current == WeatherType.SNOW.value:
            pet = with_status(pet, StatusType.FREEZE, SNOW_FREEZE_STACKS)
        side_state = replace_pet(side_state, slot, pet)
        state = replace_side(state, side_id, side_state)
    if turns > 0:
        turns -= 1
        state = state._replace(weather=pack_weather(current, turns) if turns > 0 else 0)
    return state
