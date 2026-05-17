"""Packed integer helpers for the battle runtime."""

from __future__ import annotations

from enum import IntEnum

from roco.engine.enums import Element, StatusType, WeatherType


def _pack_buff(atk_p=0, atk_m=0, def_p=0, def_m=0, spd=0, acc=0, eva=0) -> int:
    """Pack 7 buff stages into u32. Each 4 bits, signed (-6 to +6)."""

    def s(v): return (v + 6) & 0xF
    return (s(atk_p) | s(def_p) << 4 | s(spd) << 8 | s(atk_m) << 12 |
            s(def_m) << 16 | s(acc) << 20 | s(eva) << 24)


def _unpack_buff(packed: int, idx: int) -> int:
    """Unpack one buff stage."""

    return ((packed >> (idx * 4)) & 0xF) - 6


def _set_buff(packed: int, idx: int, val: int) -> int:
    clamped = max(-6, min(6, val))
    shift = idx * 4
    packed &= ~(0xF << shift)
    return packed | ((clamped + 6) & 0xF) << shift


def buff_multiplier(stage: int) -> float:
    """Buff stage to multiplier. +6=1.6, -6=0.625."""

    return 1.0 + stage * 0.10 if stage >= 0 else 1.0 / (1.0 + abs(stage) * 0.10)


def _pack_status(burn=0, poison=0, freeze=0, leech=0) -> int:
    return (burn & 0xFF) | (poison & 0xFF) << 8 | (freeze & 0xFF) << 16 | (leech & 0xFF) << 24


def _unpack_status(packed: int, t: StatusType) -> int:
    return (packed >> (t.value * 8)) & 0xFF


def _set_status(packed: int, t: StatusType, val: int) -> int:
    shift = t.value * 8
    packed &= ~(0xFF << shift)
    return packed | ((val & 0xFF) << shift)


class MarkIdx(IntEnum):
    MOISTURE = 0; DRAGON = 1; MOMENTUM = 2; WIND = 3; CHARGE = 4; SOLAR = 5; ATTACK = 6
    SLOW = 7; SPIRIT = 8; METEOR = 9; POISON = 10; THORN = 11; SLUGGISH = 12


class DevotionIdx(IntEnum):
    JIAMEI = 0; FEIDUAN = 1; CHONGJIAN = 2; KUNFU = 3; CHONGQUN = 4


def _pack_marks(**counts) -> int:
    result = 0
    for idx, value in counts.items():
        result |= (value & 0xF) << (idx.value * 4)
    return result


def _unpack_mark(packed: int, idx: MarkIdx) -> int:
    return (packed >> (idx.value * 4)) & 0xF


def _set_mark(packed: int, idx: MarkIdx, val: int) -> int:
    shift = idx.value * 4
    return (packed & ~(0xF << shift)) | ((val & 0xF) << shift)


def _pack_devotion(**counts) -> int:
    result = 0
    for idx, value in counts.items():
        result |= (value & 0xF) << (idx.value * 4)
    return result


def _unpack_devotion(packed: int, idx: DevotionIdx) -> int:
    return (packed >> (idx.value * 4)) & 0xF


def _pack_skill_counts(**counts: int) -> int:
    """Pack per-element skill usage counts. 18 elements x 4 bits = 72 bits."""

    result = 0
    for elem, cnt in counts.items():
        result |= (cnt & 0xF) << (elem.value * 4)
    return result


def _unpack_skill_count(packed: int, elem: Element) -> int:
    return (packed >> (elem.value * 4)) & 0xF


def _inc_skill_count(packed: int, elem: Element) -> int:
    shift = elem.value * 4
    cur = (packed >> shift) & 0xF
    if cur < 0xF:
        return (packed & ~(0xF << shift)) | ((cur + 1) << shift)
    return packed


def _pack_weather(wtype: WeatherType, turns: int) -> int:
    return (wtype.value & 0xF) | (turns & 0xF) << 4


def _unpack_weather(packed: int) -> tuple[WeatherType, int]:
    return WeatherType(packed & 0xF), (packed >> 4) & 0xF


def _pack_burst_entries(**slots) -> int:
    """Pack 6 slots x 6 bits each (turn 0-63)."""

    result = 0
    for slot, turn in slots.items():
        result |= (turn & 0x3F) << (slot * 6)
    return result


def _unpack_burst_entry(packed: int, slot: int) -> int:
    """Get entry turn for a slot. Returns 0 if never entered."""

    return (packed >> (slot * 6)) & 0x3F


def _set_burst_entry(packed: int, slot: int, turn: int) -> int:
    shift = slot * 6
    return (packed & ~(0x3F << shift)) | ((turn & 0x3F) << shift)


def _cooldown_at(packed: int, idx: int) -> int:
    if idx < 0 or idx >= 8:
        return 0
    return (packed >> (idx * 4)) & 0xF


def _set_cooldown(packed: int, idx: int, turns: int) -> int:
    if idx < 0 or idx >= 8:
        return packed
    shift = idx * 4
    packed &= ~(0xF << shift)
    return packed | ((max(0, min(15, turns)) & 0xF) << shift)


def _tick_cooldowns(packed: int) -> int:
    result = 0
    for idx in range(8):
        cd = _cooldown_at(packed, idx)
        if cd > 1:
            result = _set_cooldown(result, idx, cd - 1)
    return result
