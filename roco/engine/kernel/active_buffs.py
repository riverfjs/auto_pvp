"""Packed active-buff ledger for :class:`PetState.active_buffs`.

A pet's ``active_buffs`` is a single Python ``int`` holding 8 fixed
lanes of 64 bits each.  Each non-empty lane records the identity and
lifetime of one active buff::

    bits  0..31  buff_id        (pak BUFF_CONF id; 0 is sentinel = empty)
    bits 32..35  source_side    (currently 0 or 1)
    bits 36..39  source_slot    (0..7)
    bits 40..47  duration       (0..255; 0 = persistent / no tick)
    bits 48..63  reserved       (must be 0)

The packed-int / fixed-lane shape mirrors ``PetState.cooldowns`` and
``SideState.cost_mods`` so ``copy_state`` and the kernel's fixed-update
contract still hold.  All bit-shift logic lives here; callers must
never hand-edit lanes.

The current implementation ships this data layer plus a turn-end ``tick``
that decrements each non-zero ``duration`` once per round.  Lane semantics
beyond ``duration`` countdown (dispel kinds, refresh-on-reapply, immunity
derivation) stay explicit kernel work, not generated pak static data.
"""

from __future__ import annotations

from typing import Iterable


# ── lane layout constants ────────────────────────────────────────────────

LANES = 8
LANE_BITS = 64
LANE_MASK = (1 << LANE_BITS) - 1

_BUFF_ID_SHIFT = 0
_BUFF_ID_BITS = 32
_BUFF_ID_MAX = (1 << _BUFF_ID_BITS) - 1            # 0xFFFFFFFF
_BUFF_ID_MASK = _BUFF_ID_MAX

_SOURCE_SIDE_SHIFT = 32
_SOURCE_SIDE_BITS = 4
_SOURCE_SIDE_MASK = (1 << _SOURCE_SIDE_BITS) - 1   # 0xF

_SOURCE_SLOT_SHIFT = 36
_SOURCE_SLOT_BITS = 4
_SOURCE_SLOT_MASK = (1 << _SOURCE_SLOT_BITS) - 1   # 0xF

_DURATION_SHIFT = 40
_DURATION_BITS = 8
_DURATION_MAX = (1 << _DURATION_BITS) - 1          # 255
_DURATION_MASK = _DURATION_MAX

_RESERVED_SHIFT = 48
_RESERVED_MASK = ((1 << 16) - 1) << _RESERVED_SHIFT


# ── range checks ─────────────────────────────────────────────────────────


def _ensure_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(
            f"active_buffs.{name} must be int; got {type(value).__name__} {value!r}"
        )
    return value


def _ensure_buff_id(buff_id: int) -> int:
    _ensure_int("buff_id", buff_id)
    if buff_id < 1 or buff_id > _BUFF_ID_MAX:
        raise RuntimeError(
            f"active_buffs.buff_id must be 1..{_BUFF_ID_MAX} "
            f"(0 is sentinel for empty lane); got {buff_id}"
        )
    return buff_id


def _ensure_source_side(source_side: int) -> int:
    _ensure_int("source_side", source_side)
    if source_side not in (0, 1):
        raise RuntimeError(
            f"active_buffs.source_side must be 0 or 1 (Phase 5A); got {source_side}"
        )
    return source_side


def _ensure_source_slot(source_slot: int) -> int:
    _ensure_int("source_slot", source_slot)
    if source_slot < 0 or source_slot > 7:
        raise RuntimeError(
            f"active_buffs.source_slot must be 0..7; got {source_slot}"
        )
    return source_slot


def _ensure_duration(duration: int) -> int:
    _ensure_int("duration", duration)
    if duration < 0 or duration > _DURATION_MAX:
        raise RuntimeError(
            f"active_buffs.duration must be 0..{_DURATION_MAX}; got {duration}"
        )
    return duration


def _ensure_slot_idx(slot_idx: int) -> int:
    _ensure_int("slot_idx", slot_idx)
    if slot_idx < 0 or slot_idx >= LANES:
        raise RuntimeError(
            f"active_buffs.slot_idx must be 0..{LANES - 1}; got {slot_idx}"
        )
    return slot_idx


def _ensure_lane(lane: int) -> int:
    _ensure_int("lane", lane)
    if lane < 0 or lane > LANE_MASK:
        raise RuntimeError(
            f"active_buffs.lane must be 0..{LANE_MASK}; got {lane}"
        )
    return lane


def _ensure_packed(packed: int) -> int:
    _ensure_int("packed", packed)
    if packed < 0:
        raise RuntimeError(f"active_buffs.packed must be non-negative; got {packed}")
    return packed


# ── pack / unpack ────────────────────────────────────────────────────────


def pack_active_buff(buff_id: int, source_side: int, source_slot: int, duration: int) -> int:
    """Pack a non-empty lane.  Returns a 64-bit int.

    ``buff_id == 0`` is rejected: 0 is the sentinel for an empty lane and
    must be produced via :func:`remove_active_buff` or a literal ``0``
    rather than through this function.
    """
    _ensure_buff_id(buff_id)
    _ensure_source_side(source_side)
    _ensure_source_slot(source_slot)
    _ensure_duration(duration)
    return (
        (buff_id << _BUFF_ID_SHIFT)
        | (source_side << _SOURCE_SIDE_SHIFT)
        | (source_slot << _SOURCE_SLOT_SHIFT)
        | (duration << _DURATION_SHIFT)
    )


def active_buff_id(lane: int) -> int:
    _ensure_lane(lane)
    return (lane >> _BUFF_ID_SHIFT) & _BUFF_ID_MASK


def active_buff_source_side(lane: int) -> int:
    _ensure_lane(lane)
    return (lane >> _SOURCE_SIDE_SHIFT) & _SOURCE_SIDE_MASK


def active_buff_source_slot(lane: int) -> int:
    _ensure_lane(lane)
    return (lane >> _SOURCE_SLOT_SHIFT) & _SOURCE_SLOT_MASK


def active_buff_duration(lane: int) -> int:
    _ensure_lane(lane)
    return (lane >> _DURATION_SHIFT) & _DURATION_MASK


# ── multi-lane operations ────────────────────────────────────────────────


def _lane_at(packed: int, slot_idx: int) -> int:
    return (packed >> (slot_idx * LANE_BITS)) & LANE_MASK


def _clear_lane(packed: int, slot_idx: int) -> int:
    return packed & ~(LANE_MASK << (slot_idx * LANE_BITS))


def set_active_buff_slot(packed: int, slot_idx: int, lane: int) -> int:
    """Replace lane ``slot_idx`` in ``packed`` with the given lane value.

    ``lane`` may be 0 (clearing the slot) or a full 64-bit packed lane.
    Non-empty lanes must keep their reserved bits zero, and field
    sub-bits must each fall within their allowed range — this guards
    against callers stuffing junk into ``reserved`` or skipping the
    pack helper.
    """
    _ensure_packed(packed)
    _ensure_slot_idx(slot_idx)
    _ensure_lane(lane)
    if lane != 0:
        # Re-validate each field via the same range checks the pack
        # helper applies, so set_active_buff_slot is never a backdoor
        # around them.
        _ensure_buff_id(active_buff_id(lane))
        _ensure_source_side(active_buff_source_side(lane))
        _ensure_source_slot(active_buff_source_slot(lane))
        _ensure_duration(active_buff_duration(lane))
        if lane & _RESERVED_MASK:
            raise RuntimeError(
                f"active_buffs.lane reserved bits 48..63 must be zero; "
                f"got lane=0x{lane:016x}"
            )
    return _clear_lane(packed, slot_idx) | (lane << (slot_idx * LANE_BITS))


def iter_active_buffs(packed: int) -> Iterable[tuple[int, int]]:
    """Yield ``(slot_idx, lane)`` for every non-empty lane in ``packed``.

    Empty lanes (``buff_id == 0``) are skipped.  Yield order is by
    ``slot_idx`` ascending.
    """
    _ensure_packed(packed)
    for slot_idx in range(LANES):
        lane = _lane_at(packed, slot_idx)
        if active_buff_id(lane) != 0:
            yield slot_idx, lane


def add_active_buff(
    packed: int,
    buff_id: int,
    source_side: int,
    source_slot: int,
    duration: int,
) -> int:
    """Pack a new lane and place it in the first empty slot.

    Phase 5A does **not** dedupe — even if ``packed`` already contains a
    lane with the same ``buff_id``, a second call places a new lane in
    the next empty slot.  Refresh / dedupe semantics belong to the
    consumer family that adopts active buffs.

    Raises ``RuntimeError`` when all 8 lanes are occupied.
    """
    _ensure_packed(packed)
    lane = pack_active_buff(buff_id, source_side, source_slot, duration)
    for slot_idx in range(LANES):
        if active_buff_id(_lane_at(packed, slot_idx)) == 0:
            return _clear_lane(packed, slot_idx) | (lane << (slot_idx * LANE_BITS))
    raise RuntimeError(
        f"active_buffs at capacity {LANES}; no empty lane left to add "
        f"buff_id={buff_id}"
    )


def remove_active_buff(packed: int, slot_idx: int) -> int:
    """Clear the lane at ``slot_idx``.  Other lanes are unaffected.

    Removing an already-empty slot is a no-op (returns ``packed``
    unchanged) — the slot index must still be in range.
    """
    _ensure_packed(packed)
    _ensure_slot_idx(slot_idx)
    return _clear_lane(packed, slot_idx)


def effective_immunity_flags(packed: int) -> int:
    """OR every non-empty lane's immunity contribution into a single flag word.

    The lookup table comes from :mod:`roco.generated.buff_immunity_table`,
    which is derived from pak ``BUFF_CONF.desc`` immunity phrases.
    A ``buff_id`` absent from the table contributes nothing — silent zero
    is correct here because not every active buff is an immunity carrier.

    Pure function: no PetState dependency; callers do
    ``effective_immunity_flags(pet.active_buffs)``.  Empty ledger returns 0,
    so any code path that consults this on an unbuffed pet is
    behaviour-neutral.
    """
    # Imported lazily to keep the active_buffs module free of generated/
    # imports at module load time — only consumers of immunity pay the
    # cost.  The table itself is a plain dict literal, no side effects.
    from roco.generated.buff_immunity_table import BUFF_IMMUNITY_TABLE

    _ensure_packed(packed)
    flags = 0
    for _slot_idx, lane in iter_active_buffs(packed):
        flags |= BUFF_IMMUNITY_TABLE.get(active_buff_id(lane), 0)
    return flags


def tick_active_buffs(packed: int) -> int:
    """Decrement ``duration`` on every non-empty lane.

    Lane semantics:

    * ``duration == 0`` — persistent; lane is untouched.
    * ``duration > 1``  — duration decreases by 1; other fields unchanged.
    * ``duration == 1`` — lane expires and is cleared (all 64 bits zero).

    Empty lanes are also untouched.  Pure function; no side effects.
    """
    _ensure_packed(packed)
    result = packed
    for slot_idx in range(LANES):
        lane = _lane_at(result, slot_idx)
        buff_id = active_buff_id(lane)
        if buff_id == 0:
            continue
        duration = active_buff_duration(lane)
        if duration == 0:
            continue
        if duration == 1:
            result = _clear_lane(result, slot_idx)
            continue
        # Clear old duration bits and write (duration - 1) back in place.
        new_duration = duration - 1
        cleared = lane & ~(_DURATION_MASK << _DURATION_SHIFT)
        new_lane = cleared | (new_duration << _DURATION_SHIFT)
        result = _clear_lane(result, slot_idx) | (new_lane << (slot_idx * LANE_BITS))
    return result
