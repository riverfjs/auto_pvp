"""Phase 5C-i: 20030160 zero-energy auto self-switch.

The pak buff_id ``20030160`` is referenced by ability ``200166`` (星地善良)
in two ``skill_result`` entries (cast_moment 11 and 26).  ``BUFF_CONF``
provides no self-text; the only pak evidence is the referencing
ability's desc:

    回合结束时，若场上的己方精灵能量等于0，自己立即替换此精灵。

This file proves the runtime path that delivers that semantic at
``TIMING_AFTER_MOVE`` (cast_moment 11).  Two unit tests guard the
boundary cases (zero energy → switch; positive energy → no switch);
the integration test exercises the full ``mechanics.update`` chain
through skill cost deduction and the ``ctx.actor_energy`` refresh that
Phase 5C-i introduced — without that refresh, ``ctx.actor_energy`` at
``TIMING_AFTER_MOVE`` would be the pre-cost value and the buff would
never fire.

cast_moment 26 (``TIMING_PASSIVE_COND``) is decoder-classified to the
same handler but currently runtime-inert — no dispatcher runs ability
rows at that timing yet.  That's deferred to a future phase; this
file does not test cast_moment 26.
"""

from __future__ import annotations

import pytest

from roco.common.constants import STARTING_ENERGY
from roco.engine.common.choices import SIDE_A, SIDE_B, move_choice
from roco.engine.kernel.catalog import SKILL_ENERGY
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.mechanics import _run_ability_timing, update
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.engine.kernel.state import (
    make_state,
    replace_pet,
)
from roco.generated import catalog_debug as debug
from roco.generated import catalog_hot as hot


_STAR_ABILITY_PET = 194    # 粉粉星 — carries ability 200166 星地善良
_BENCH_PET = 195           # 小皮球 — also carries 200166 but used here as bench
_OPPONENT_PET = 1          # any sane pet; SIDE_B's choice runs in parallel

# A skill whose ``SKILL_ENERGY`` equals ``STARTING_ENERGY`` (= 10), so an
# unmodified actor drains to exactly 0 in one move.  Picked to have low
# power so the opponent doesn't die before the integration test gets to
# observe the auto-switch.  ``mechanics`` doesn't enforce pet-skill
# compatibility — the slot just stores a skill_id — so we override the
# default loadout via ``team_a_moves``.
_FULL_DRAIN_SKILL = 70     # cost 10, power 1
_FULL_DRAIN_SLOT = 0


def _opponent_default_move_slot() -> int:
    """Pick any non-zero skill slot on the opponent's default loadout."""
    moves = hot.PET_SKILLS[_OPPONENT_PET]
    for idx, sid in enumerate(moves):
        if sid > 0:
            return idx
    raise RuntimeError(f"opponent pet {_OPPONENT_PET} has no usable skill")


# ── integration: ctx.actor_energy refresh + base_id seed + force_switch ───


def test_zero_energy_after_move_triggers_auto_switch():
    """End-to-end: actor starts at ``STARTING_ENERGY`` (= 10) and uses a
    cost-10 skill, so post-cost energy is exactly 0.  The ability row
    for buff 20030160 must fire at TIMING_AFTER_MOVE and the side-A
    active slot must change to a non-fainted bench pet.

    This is the **sensitivity test** for the Phase 5C-i
    ``ctx.actor_energy`` refresh: without the refresh, ``ctx.actor_energy``
    stays at the pre-cost value (10) the whole way through, the
    auto-switch op sees 10 > 0, no switch happens.  With the refresh,
    ``ctx.actor_energy`` is set to the actor's post-cost
    ``current_energy`` (= 0) just before TIMING_AFTER_MOVE, the op
    fires, and ``apply_after_move`` consumes ``ctx.force_switch``.
    """
    cost = hot.SKILLS[_FULL_DRAIN_SKILL][SKILL_ENERGY]
    assert cost == STARTING_ENERGY, (
        "fixture pre-condition: skill cost must equal STARTING_ENERGY so "
        "the actor drains to exactly 0 without manual energy tweaks"
    )

    state = make_state(
        (_STAR_ABILITY_PET, _BENCH_PET),
        (_OPPONENT_PET,),
        # Place the cost-10 drain skill in slot 0 of side A's loadout;
        # mechanics doesn't enforce pet-skill compatibility, only the
        # slot mapping.
        team_a_moves=((_FULL_DRAIN_SKILL,),),
        rng_seed=1,
    )
    assert state.side_a.active == 0
    assert state.side_a.pets[0].current_energy == STARTING_ENERGY

    result = update(
        state,
        move_choice(_FULL_DRAIN_SLOT),
        move_choice(_opponent_default_move_slot()),
    )

    # Core assertion: side_a's active slot moved off the actor.  The
    # actor's ``current_energy`` after the move may not be 0 — ability
    # 200166 also carries an energy-heal row at cast_moment 11 (effect
    # 20520080) that runs in the same TIMING_AFTER_MOVE dispatch and
    # writes ``ctx.energy_gain``, which ``apply_after_move`` folds back
    # into ``current_energy`` after the auto-switch op has already
    # consumed ``ctx.actor_energy``.  What this test exercises is that
    # ``ctx.actor_energy`` reflects the *post-cost* value when the
    # auto-switch op reads it (Phase 5C-i fix), not the pre-cost value.
    assert result.state.side_a.active != 0
    new_active = result.state.side_a.active
    assert not result.state.side_a.pets[new_active].fainted


# ── unit: TIMING_AFTER_MOVE ability row sets ctx.force_switch on 0 ───────


def _seeded_state_with_star_ability_actor(bench_pet: int = _BENCH_PET):
    """Build a state with the 星地善良 actor + a non-fainted bench partner."""
    state = make_state(
        (_STAR_ABILITY_PET, bench_pet),
        (_OPPONENT_PET,),
        rng_seed=1,
    )
    return state


def test_zero_energy_unit_after_move_sets_force_switch():
    """Skip the cost-deduction logic: hand-build ctx with actor_energy=0,
    fire TIMING_AFTER_MOVE, assert ctx.force_switch flips to 1, and
    confirm apply_after_move's _auto_switch consumes the flag."""
    from roco.engine.kernel.op_rows import TIMING_AFTER_MOVE

    state = _seeded_state_with_star_ability_actor()
    actor = state.side_a.pets[0]

    ctx = StageCtx()
    ctx.reset(SIDE_A, 0, SIDE_B, 0, 0)
    ctx.actor_energy = 0

    _run_ability_timing(actor, TIMING_AFTER_MOVE, ctx)
    assert ctx.force_switch == 1

    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    assert new_state.side_a.active != 0


def test_positive_energy_no_switch():
    """Same hand-built fixture, but actor_energy stays > 0.  The op must
    leave ctx.force_switch == 0 and apply_after_move must not switch."""
    from roco.engine.kernel.op_rows import TIMING_AFTER_MOVE

    state = _seeded_state_with_star_ability_actor()
    actor = state.side_a.pets[0]

    ctx = StageCtx()
    ctx.reset(SIDE_A, 0, SIDE_B, 0, 0)
    ctx.actor_energy = 50

    _run_ability_timing(actor, TIMING_AFTER_MOVE, ctx)
    assert ctx.force_switch == 0

    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    assert new_state.side_a.active == 0


def test_no_replacement_no_crash():
    """When the only available bench pet is fainted, _auto_switch must
    return the state unchanged rather than raise.  This guards against
    a real-game scenario where 星地善良 triggers but no bench is alive
    to receive the switch."""
    from roco.engine.kernel.op_rows import TIMING_AFTER_MOVE

    state = _seeded_state_with_star_ability_actor()
    # Knock the bench pet down to fainted.
    bench = state.side_a.pets[1]._replace(current_hp=0, fainted=1)
    state = state._replace(side_a=replace_pet(state.side_a, 1, bench))
    actor = state.side_a.pets[0]

    ctx = StageCtx()
    ctx.reset(SIDE_A, 0, SIDE_B, 0, 0)
    ctx.actor_energy = 0
    _run_ability_timing(actor, TIMING_AFTER_MOVE, ctx)
    assert ctx.force_switch == 1

    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    # No crash; active slot stays put because the only bench pet is fainted.
    assert new_state.side_a.active == 0
