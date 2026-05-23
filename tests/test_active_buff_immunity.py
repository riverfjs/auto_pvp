"""Phase 5B-mini: ledger-driven immunity consumer smoke tests.

These tests manually seed ``PetState.active_buffs`` with the two pak buff
ids Phase 2A registered in ``BUFF_IMMUNITY_TABLE`` (20030010 / 20030011)
and verify that the runtime immunity consumers added in Phase 5B-mini
honour the flags:

* ``apply_status_effect`` rejects poison / burn / freeze / leech when
  the target carries a matching IMMUNITY_* flag via its active buffs.
* ``apply_after_move`` honours IMMUNITY_FORCE_SWITCH against
  ``ctx.force_enemy_switch`` (the "blow away" path).

By design these tests do **not** exercise any code that *applies*
20030010 / 20030011 to a pet — Phase 5B-mini ships zero buff-application
runtime.  The buffs reach ``active_buffs`` only because the tests pack
them into the ledger by hand.  No gap rows are affected by this phase.
"""

from __future__ import annotations

from roco.common.enums import StatusFlag, StatusType
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.active_buffs import (
    effective_immunity_flags,
    pack_active_buff,
)
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.engine.kernel.residual.status_ticks import apply_status_effect
from roco.engine.kernel.state import (
    PetState,
    has_status,
    make_state,
    replace_pet,
    replace_side,
    side,
    status_stack,
)
from roco.generated.buff_immunity_table import (
    BUFF_IMMUNITY_TABLE,
    IMMUNITY_BURN,
    IMMUNITY_FORCE_SWITCH,
    IMMUNITY_FREEZE,
    IMMUNITY_LEECH,
    IMMUNITY_POISON,
)


# ── effective_immunity_flags ─────────────────────────────────────────────


def test_empty_ledger_yields_no_flags():
    assert effective_immunity_flags(0) == 0


def test_single_buff_yields_table_flag():
    lane = pack_active_buff(buff_id=20030010, source_side=0, source_slot=0, duration=0)
    assert effective_immunity_flags(lane) == BUFF_IMMUNITY_TABLE[20030010]
    assert effective_immunity_flags(lane) & IMMUNITY_FORCE_SWITCH


def test_full_immunity_buff_covers_all_listed_statuses():
    lane = pack_active_buff(buff_id=20030011, source_side=0, source_slot=0, duration=0)
    flags = effective_immunity_flags(lane)
    for needed in (
        IMMUNITY_FORCE_SWITCH,
        IMMUNITY_POISON,
        IMMUNITY_BURN,
        IMMUNITY_FREEZE,
        IMMUNITY_LEECH,
    ):
        assert flags & needed, f"missing {needed:#x} in {flags:#x}"


def test_unknown_buff_id_contributes_zero():
    # Pak buff with no immunity entry: e.g. 20030160 (auto-switch family).
    # It is in pak BUFF_CONF but not in BUFF_IMMUNITY_TABLE, so the ledger
    # entry must OR in zero — not raise, not silently fall back to a
    # different table.
    assert 20030160 not in BUFF_IMMUNITY_TABLE
    lane = pack_active_buff(buff_id=20030160, source_side=0, source_slot=0, duration=0)
    assert effective_immunity_flags(lane) == 0


def test_mixed_ledger_ors_contributions():
    lane_a = pack_active_buff(buff_id=20030010, source_side=0, source_slot=0, duration=0)
    lane_b = pack_active_buff(buff_id=20030011, source_side=1, source_slot=3, duration=5)
    packed = lane_a | (lane_b << 64)
    flags = effective_immunity_flags(packed)
    # Should include every bit either buff contributes.
    assert flags == BUFF_IMMUNITY_TABLE[20030010] | BUFF_IMMUNITY_TABLE[20030011]


# ── apply_status_effect honours ledger immunity ──────────────────────────


def _seed_active_buff(state, side_id, slot, buff_id):
    target_side = side(state, side_id)
    target = target_side.pets[slot]
    lane = pack_active_buff(buff_id=buff_id, source_side=side_id, source_slot=slot, duration=0)
    return replace_side(
        state,
        side_id,
        replace_pet(target_side, slot, target._replace(active_buffs=lane)),
    )


def test_apply_status_effect_blocks_burn_when_immune():
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_B, 0, 20030011)
    target = side(state, SIDE_B).pets[0]
    result = apply_status_effect(target, StatusType.BURN, StatusFlag.BURN, 3, SIDE_A, 0)
    assert status_stack(result, StatusType.BURN) == 0
    assert not has_status(result, StatusFlag.BURN)


def test_apply_status_effect_blocks_poison_when_immune():
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_B, 0, 20030011)
    target = side(state, SIDE_B).pets[0]
    result = apply_status_effect(target, StatusType.POISON, StatusFlag.POISON, 5, SIDE_A, 0)
    assert status_stack(result, StatusType.POISON) == 0


def test_apply_status_effect_blocks_freeze_when_immune():
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_B, 0, 20030011)
    target = side(state, SIDE_B).pets[0]
    result = apply_status_effect(target, StatusType.FREEZE, StatusFlag.FREEZE, 1, SIDE_A, 0)
    assert status_stack(result, StatusType.FREEZE) == 0


def test_apply_status_effect_blocks_leech_when_immune():
    """Active-buff immunity covers leech even though the type-based path
    deliberately ignores it (pak 20030011 lists 寄生 explicitly)."""
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_B, 0, 20030011)
    target = side(state, SIDE_B).pets[0]
    result = apply_status_effect(target, StatusType.LEECH, StatusFlag.LEECH, 2, SIDE_A, 0)
    assert status_stack(result, StatusType.LEECH) == 0
    # The leech source side/slot fields stay unset on the immune target.
    assert result.leech_source_side == -1
    assert result.leech_source_slot == -1


def test_apply_status_effect_force_switch_only_buff_does_not_block_status():
    """20030010 only carries IMMUNITY_FORCE_SWITCH; it must NOT block burn."""
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_B, 0, 20030010)
    target = side(state, SIDE_B).pets[0]
    result = apply_status_effect(target, StatusType.BURN, StatusFlag.BURN, 2, SIDE_A, 0)
    # Burn should still apply because 20030010 has no IMMUNITY_BURN bit.
    assert status_stack(result, StatusType.BURN) >= 1


def test_apply_status_effect_passes_through_when_no_active_buff():
    """Empty ledger must leave existing type-based logic unchanged."""
    state = make_state((1, 2, 3), (4, 5, 6))
    target = side(state, SIDE_B).pets[0]
    assert target.active_buffs == 0
    result = apply_status_effect(target, StatusType.BURN, StatusFlag.BURN, 2, SIDE_A, 0)
    # Result depends only on the existing type-based immunity, not on our
    # new path; since the test pet has no fire-type element, burn applies.
    assert status_stack(result, StatusType.BURN) >= 1


# ── force_switch immunity via ctx.force_enemy_switch ─────────────────────


def _make_ctx_for_force_enemy_switch():
    ctx = StageCtx()
    ctx.force_enemy_switch = 1
    return ctx


def test_force_enemy_switch_blocked_by_immunity_buff():
    """Target carries 20030010 (force-switch-only).  The actor's
    force_enemy_switch must not change the target's active slot."""
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_B, 0, 20030010)
    active_before = side(state, SIDE_B).active
    ctx = _make_ctx_for_force_enemy_switch()
    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    assert side(new_state, SIDE_B).active == active_before


def test_force_enemy_switch_succeeds_without_immunity():
    """No active buff => existing _auto_switch path runs."""
    state = make_state((1, 2, 3), (4, 5, 6))
    assert side(state, SIDE_B).pets[0].active_buffs == 0
    active_before = side(state, SIDE_B).active
    ctx = _make_ctx_for_force_enemy_switch()
    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    # The auto-switch helper moves the active slot to the next non-fainted
    # pet on the same side.
    assert side(new_state, SIDE_B).active != active_before


def test_self_force_switch_ignores_immunity():
    """``ctx.force_switch`` is self-initiated.  Even if the actor carries
    IMMUNITY_FORCE_SWITCH, the switch must still happen — pak's
    ``免疫吹飞`` only protects against being blown away by the opponent."""
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_buff(state, SIDE_A, 0, 20030010)
    active_before = side(state, SIDE_A).active
    ctx = StageCtx()
    ctx.force_switch = 1
    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    assert side(new_state, SIDE_A).active != active_before
