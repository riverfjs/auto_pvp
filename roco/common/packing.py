"""Packed integer helpers shared across kernel, compiler, and test layers."""

from __future__ import annotations

from roco.common.constants import BPS
from roco.common.enums import Element, StatusType, WeatherType
from roco.common.mark_indices import DevotionIdx, MarkIdx

BUFF_UNIT_BPS = 100
BUFF_LANE_BITS = 8
BUFF_LANE_MASK = (1 << BUFF_LANE_BITS) - 1
BUFF_STAT_BITS = BUFF_LANE_BITS * 2
BUFF_ATK_PHYS = 0
BUFF_ATK_MAG = 1
BUFF_DEF_PHYS = 2
BUFF_DEF_MAG = 3
BUFF_SPEED = 4


def _pack_buff(atk_p=0, atk_m=0, def_p=0, def_m=0, spd=0, acc=0, eva=0) -> int:
    """Pack stat buff deltas as BPS up/down lanes.

    The old stage-shaped signature is kept for fixtures. Each input unit means
    10%, and is translated to positive or negative BPS in the packed lane.
    """

    packed = 0
    for idx, value in enumerate((atk_p, atk_m, def_p, def_m, spd, acc, eva)):
        packed = _add_buff_bps(packed, idx, int(value) * 1000)
    return packed


def _unpack_buff(packed: int, idx: int) -> int:
    """Unpack one buff lane as approximate 10% stages for debug/tests."""

    return _buff_net_bps(packed, idx) // 1000


def _set_buff(packed: int, idx: int, val: int) -> int:
    shift = idx * BUFF_STAT_BITS
    packed &= ~(0xFFFF << shift)
    return _add_buff_bps(packed, idx, int(val) * 1000)


def buff_multiplier(stage: int) -> float:
    """Buff stage to multiplier. +6=1.6, -6=0.625."""

    return 1.0 + stage * 0.10 if stage >= 0 else 1.0 / (1.0 + abs(stage) * 0.10)


def _buff_lane(packed: int, idx: int) -> tuple[int, int]:
    shift = idx * BUFF_STAT_BITS
    up = (packed >> shift) & BUFF_LANE_MASK
    down = (packed >> (shift + BUFF_LANE_BITS)) & BUFF_LANE_MASK
    return up * BUFF_UNIT_BPS, down * BUFF_UNIT_BPS


def _buff_net_bps(packed: int, idx: int) -> int:
    up, down = _buff_lane(packed, idx)
    return up - down


def _add_buff_bps(packed: int, idx: int, delta_bps: int) -> int:
    shift = idx * BUFF_STAT_BITS
    up_units = (packed >> shift) & BUFF_LANE_MASK
    down_units = (packed >> (shift + BUFF_LANE_BITS)) & BUFF_LANE_MASK
    units = min(BUFF_LANE_MASK, abs(int(delta_bps)) // BUFF_UNIT_BPS)
    if delta_bps >= 0:
        up_units = min(BUFF_LANE_MASK, up_units + units)
    else:
        down_units = min(BUFF_LANE_MASK, down_units + units)
    packed &= ~(0xFFFF << shift)
    return packed | (up_units << shift) | (down_units << (shift + BUFF_LANE_BITS))


def _merge_buff_delta(packed: int, delta: int) -> int:
    for idx in range(7):
        up, down = _buff_lane(delta, idx)
        if up:
            packed = _add_buff_bps(packed, idx, up)
        if down:
            packed = _add_buff_bps(packed, idx, -down)
    return packed


def _add_to_positive_buff_lanes(delta: int, extra_bps: int) -> int:
    for idx in range(7):
        up, _ = _buff_lane(delta, idx)
        if up:
            delta = _add_buff_bps(delta, idx, extra_bps)
    return delta


def _add_to_negative_buff_lanes(packed: int, extra_bps: int) -> int:
    for idx in range(7):
        _, down = _buff_lane(packed, idx)
        if down:
            packed = _add_buff_bps(packed, idx, -extra_bps)
    return packed


def _clear_buff_lanes(packed: int, *, positive: bool, negative: bool) -> int:
    for idx in range(7):
        shift = idx * BUFF_STAT_BITS
        if positive:
            packed &= ~(BUFF_LANE_MASK << shift)
        if negative:
            packed &= ~(BUFF_LANE_MASK << (shift + BUFF_LANE_BITS))
    return packed


def stat_ratio_bps(attacker_buffs: int, attack_idx: int, defender_buffs: int, defense_idx: int) -> int:
    """Stat modifier: (1 + atk_up + def_down) / (1 + atk_down + def_up)."""

    atk_up, atk_down = _buff_lane(attacker_buffs, attack_idx)
    def_up, def_down = _buff_lane(defender_buffs, defense_idx)
    numerator = BPS + atk_up + def_down
    denominator = max(1, BPS + atk_down + def_up)
    return numerator * BPS // denominator


def _pack_status(burn=0, poison=0, freeze=0, leech=0) -> int:
    return (burn & 0xFF) | (poison & 0xFF) << 8 | (freeze & 0xFF) << 16 | (leech & 0xFF) << 24


def _unpack_status(packed: int, t: StatusType) -> int:
    return (packed >> (t.value * 8)) & 0xFF


def _set_status(packed: int, t: StatusType, val: int) -> int:
    shift = t.value * 8
    packed &= ~(0xFF << shift)
    return packed | ((val & 0xFF) << shift)


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


def _set_devotion(packed: int, idx: DevotionIdx, val: int) -> int:
    shift = idx.value * 4
    return (packed & ~(0xF << shift)) | ((val & 0xF) << shift)


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


def _unpack_u8_count(packed: int, index: int) -> int:
    if index < 0:
        return 0
    return (packed >> (index * 8)) & 0xFF


def _inc_u8_count(packed: int, index: int) -> int:
    if index < 0:
        return packed
    shift = index * 8
    cur = (packed >> shift) & 0xFF
    if cur < 0xFF:
        return (packed & ~(0xFF << shift)) | ((cur + 1) << shift)
    return packed


def _add_element_nibble(packed: int, elem: Element, amount: int) -> int:
    shift = elem.value * 4
    cur = (packed >> shift) & 0xF
    return (packed & ~(0xF << shift)) | (min(0xF, cur + max(0, int(amount))) << shift)


def _unpack_element_u8(packed: int, elem: Element) -> int:
    return (packed >> (elem.value * 8)) & 0xFF


def _add_element_u8(packed: int, elem: Element, amount: int) -> int:
    shift = elem.value * 8
    cur = (packed >> shift) & 0xFF
    return (packed & ~(0xFF << shift)) | (min(0xFF, cur + max(0, int(amount))) << shift)


def _max_element_u8(packed: int, elem: Element, amount: int) -> int:
    shift = elem.value * 8
    cur = (packed >> shift) & 0xFF
    return (packed & ~(0xFF << shift)) | (max(cur, min(0xFF, max(0, int(amount)))) << shift)


def _merge_element_nibbles(packed: int, delta: int) -> int:
    for elem in Element:
        amount = _unpack_skill_count(delta, elem)
        if amount:
            packed = _add_element_nibble(packed, elem, amount)
    return packed


def _merge_element_u8(packed: int, delta: int) -> int:
    for elem in Element:
        amount = _unpack_element_u8(delta, elem)
        if amount:
            packed = _add_element_u8(packed, elem, amount)
    return packed


def _merge_element_u8_max(packed: int, delta: int) -> int:
    for elem in Element:
        amount = _unpack_element_u8(delta, elem)
        if amount:
            packed = _max_element_u8(packed, elem, amount)
    return packed


def _clear_element_u8_mask(packed: int, mask: int) -> int:
    for elem in Element:
        if mask & (1 << elem.value):
            packed &= ~(0xFF << (elem.value * 8))
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
