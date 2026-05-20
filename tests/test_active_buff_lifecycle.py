"""Phase 5A active-buff lifecycle: data layer + turn-end tick.

The lifecycle layer in :mod:`roco.engine.kernel.active_buffs` is pure
integer manipulation; almost every test below operates on packed ints
directly.  The last test reaches into a real ``KernelState`` to prove
that ``_tick_side_turn_state`` decrements a manually-inserted active
buff at turn-end without disturbing any other lane bits.

No dispel / immunity behaviour is exercised — both are explicitly out
of scope for Phase 5A.
"""

from __future__ import annotations

import pytest

from roco.engine.kernel.active_buffs import (
    LANES,
    active_buff_duration,
    active_buff_id,
    active_buff_source_side,
    active_buff_source_slot,
    add_active_buff,
    iter_active_buffs,
    pack_active_buff,
    remove_active_buff,
    set_active_buff_slot,
    tick_active_buffs,
)
from roco.engine.kernel.residual.turn_end import _tick_side_turn_state
from roco.engine.kernel.state import make_state


# ── pack / unpack ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "buff_id, source_side, source_slot, duration",
    [
        (1, 0, 0, 0),
        (0xFF, 1, 7, 1),
        (0xFFFF, 0, 3, 8),
        (0xFFFFFFF, 1, 5, 200),
        (0xFFFFFFFF, 1, 7, 255),
        (20030010, 0, 1, 3),      # Phase 2A immunity sample
        (20030011, 1, 2, 10),
        (20400690, 0, 4, 50),     # pak prefix_2040 high-id sample
    ],
)
def test_pack_unpack_roundtrip(buff_id, source_side, source_slot, duration):
    lane = pack_active_buff(buff_id, source_side, source_slot, duration)
    assert active_buff_id(lane) == buff_id
    assert active_buff_source_side(lane) == source_side
    assert active_buff_source_slot(lane) == source_slot
    assert active_buff_duration(lane) == duration
    # Reserved bits 48..63 must round-trip as zero.
    assert (lane >> 48) == 0


def test_empty_lane_id_zero():
    assert active_buff_id(0) == 0


# ── add / overflow ───────────────────────────────────────────────────────


def test_add_active_buff_fills_first_empty_slot():
    packed = 0
    packed = add_active_buff(packed, buff_id=20030010, source_side=0, source_slot=2, duration=5)
    # Manually clear slot 0 to leave a gap at index 0 with slot 1 still empty
    # and slot 2 occupied.  Then add a new buff: should fill slot 0, not slot 1.
    packed_with_gap_at_0 = (packed >> 64) << 128  # move first occupied lane to slot 2
    next_packed = add_active_buff(packed_with_gap_at_0, 99, 1, 3, 7)
    # Slot 0 should now carry the new buff.
    slot_0_lane = next_packed & ((1 << 64) - 1)
    assert active_buff_id(slot_0_lane) == 99
    assert active_buff_source_side(slot_0_lane) == 1
    assert active_buff_source_slot(slot_0_lane) == 3
    assert active_buff_duration(slot_0_lane) == 7


def test_add_active_buff_overflow_raises():
    packed = 0
    for i in range(LANES):
        packed = add_active_buff(packed, buff_id=1000 + i, source_side=0, source_slot=i, duration=1)
    with pytest.raises(RuntimeError, match="capacity 8"):
        add_active_buff(packed, buff_id=9999, source_side=0, source_slot=0, duration=1)


# ── tick semantics ────────────────────────────────────────────────────────


def test_persistent_slot_survives_tick():
    lane = pack_active_buff(buff_id=42, source_side=0, source_slot=0, duration=0)
    packed = lane  # slot 0
    assert tick_active_buffs(packed) == packed


def test_decrement_slot():
    lane = pack_active_buff(buff_id=42, source_side=0, source_slot=0, duration=5)
    packed = lane
    ticked = tick_active_buffs(packed)
    slot_0_lane = ticked & ((1 << 64) - 1)
    assert active_buff_id(slot_0_lane) == 42
    assert active_buff_source_side(slot_0_lane) == 0
    assert active_buff_source_slot(slot_0_lane) == 0
    assert active_buff_duration(slot_0_lane) == 4


def test_expiring_slot_clears():
    lane = pack_active_buff(buff_id=42, source_side=0, source_slot=0, duration=1)
    packed = lane
    ticked = tick_active_buffs(packed)
    assert ticked == 0


def test_mixed_slots_tick_independently():
    persistent = pack_active_buff(buff_id=1, source_side=0, source_slot=0, duration=0)
    decrementing = pack_active_buff(buff_id=2, source_side=1, source_slot=1, duration=3)
    expiring = pack_active_buff(buff_id=3, source_side=0, source_slot=2, duration=1)
    packed = persistent | (decrementing << 64) | (expiring << 128)
    ticked = tick_active_buffs(packed)
    # Slot 0: persistent unchanged.
    assert (ticked & ((1 << 64) - 1)) == persistent
    # Slot 1: duration 3 -> 2.
    new_lane_1 = (ticked >> 64) & ((1 << 64) - 1)
    assert active_buff_id(new_lane_1) == 2
    assert active_buff_source_side(new_lane_1) == 1
    assert active_buff_source_slot(new_lane_1) == 1
    assert active_buff_duration(new_lane_1) == 2
    # Slot 2: expired, all bits cleared.
    new_lane_2 = (ticked >> 128) & ((1 << 64) - 1)
    assert new_lane_2 == 0
    # Higher slots remain empty.
    assert (ticked >> 192) == 0


# ── remove / iter ─────────────────────────────────────────────────────────


def test_remove_active_buff():
    a = pack_active_buff(buff_id=10, source_side=0, source_slot=0, duration=4)
    b = pack_active_buff(buff_id=20, source_side=1, source_slot=1, duration=2)
    packed = a | (b << 64)
    cleared = remove_active_buff(packed, slot_idx=0)
    assert (cleared & ((1 << 64) - 1)) == 0
    assert ((cleared >> 64) & ((1 << 64) - 1)) == b


def test_iter_active_buffs_skips_empty():
    a = pack_active_buff(buff_id=10, source_side=0, source_slot=0, duration=4)
    b = pack_active_buff(buff_id=20, source_side=1, source_slot=1, duration=2)
    # Place at slots 0 and 2 (leave slot 1 empty).
    packed = a | (b << 128)
    seen = list(iter_active_buffs(packed))
    assert [(idx, active_buff_id(lane)) for idx, lane in seen] == [(0, 10), (2, 20)]


# ── set_active_buff_slot validation ──────────────────────────────────────


def test_set_active_buff_slot_rejects_bad_idx():
    with pytest.raises(RuntimeError, match="slot_idx"):
        set_active_buff_slot(0, slot_idx=8, lane=0)
    with pytest.raises(RuntimeError, match="slot_idx"):
        set_active_buff_slot(0, slot_idx=-1, lane=0)


def test_set_active_buff_slot_rejects_oversized_lane():
    with pytest.raises(RuntimeError, match="lane"):
        set_active_buff_slot(0, slot_idx=0, lane=(1 << 64))
    with pytest.raises(RuntimeError, match="lane"):
        set_active_buff_slot(0, slot_idx=0, lane=-1)


def test_set_active_buff_slot_rejects_reserved_bits():
    lane = pack_active_buff(buff_id=42, source_side=0, source_slot=0, duration=5)
    polluted = lane | (1 << 48)  # set first reserved bit
    with pytest.raises(RuntimeError, match="reserved bits"):
        set_active_buff_slot(0, slot_idx=0, lane=polluted)


def test_set_active_buff_slot_rejects_negative_packed():
    lane = pack_active_buff(buff_id=42, source_side=0, source_slot=0, duration=5)
    with pytest.raises(RuntimeError, match="packed"):
        set_active_buff_slot(-1, slot_idx=0, lane=lane)


# ── pack input validation ────────────────────────────────────────────────


def test_pack_rejects_zero_buff_id():
    with pytest.raises(RuntimeError, match="buff_id"):
        pack_active_buff(buff_id=0, source_side=0, source_slot=0, duration=0)


def test_pack_rejects_oversized_buff_id():
    with pytest.raises(RuntimeError, match="buff_id"):
        pack_active_buff(buff_id=1 << 32, source_side=0, source_slot=0, duration=0)


def test_pack_rejects_invalid_source_side():
    with pytest.raises(RuntimeError, match="source_side"):
        pack_active_buff(buff_id=1, source_side=2, source_slot=0, duration=0)


def test_pack_rejects_oversized_source_slot():
    with pytest.raises(RuntimeError, match="source_slot"):
        pack_active_buff(buff_id=1, source_side=0, source_slot=8, duration=0)


def test_pack_rejects_oversized_duration():
    with pytest.raises(RuntimeError, match="duration"):
        pack_active_buff(buff_id=1, source_side=0, source_slot=0, duration=256)


# ── turn-end integration ─────────────────────────────────────────────────


def test_turn_end_ticks_active_buffs():
    """A clean state with one duration=3 buff on a single pet must have
    that lane's duration become 2 after one ``_tick_side_turn_state`` call,
    with every other bit of the lane preserved.
    """
    state = make_state((1, 2, 3), (4, 5, 6))
    # Build a single active buff lane on side_a active pet (slot 0).
    lane_before = pack_active_buff(buff_id=20030011, source_side=0, source_slot=0, duration=3)
    active_pet = state.side_a.pets[0]._replace(active_buffs=lane_before)
    side_a_with_buff = state.side_a._replace(
        pets=(active_pet, state.side_a.pets[1], state.side_a.pets[2])
    )
    new_side_a = _tick_side_turn_state(side_a_with_buff)
    lane_after = new_side_a.pets[0].active_buffs
    # Identity bits unchanged.
    assert active_buff_id(lane_after) == 20030011
    assert active_buff_source_side(lane_after) == 0
    assert active_buff_source_slot(lane_after) == 0
    # Duration decremented by exactly 1.
    assert active_buff_duration(lane_after) == 2
    # Reserved bits stayed zero.
    assert (lane_after >> 48) == 0
    # Other pets on the side stayed empty.
    assert new_side_a.pets[1].active_buffs == 0
    assert new_side_a.pets[2].active_buffs == 0
