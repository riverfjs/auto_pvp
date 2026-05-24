"""Phase 5C-iii boundary 4: end-to-end residual heal on status damage.

仁心 (ability 200152) heals on enemy BURN damage; 耐活王 (ability 200240)
heals on enemy POISON damage.  These are the four ack rows that
pak-derived ability flag semantics cover; the runtime path through
``tick_status`` already consumes ``HEAL_ON_BURN_DAMAGE`` /
``HEAL_ON_POISON_DAMAGE`` bits in
``roco/engine/kernel/residual/status_ticks.py``.

The tests seed BURN / POISON status onto the enemy active pet by hand
and call ``end_turn`` (the public residual entry point) — they do not
construct a full move + status-applying skill, since that would be
exercising the status-application path, not the heal-on-tick path.
"""

from __future__ import annotations

from roco.common.enums import AbilityFlag, StatusType
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.residual.turn_end import end_turn
from roco.engine.kernel.state import (
    make_state,
    replace_pet,
    replace_side,
    side,
    with_status,
)
from roco.generated import catalog_hot as hot
from roco.engine.kernel.catalog import STAT_HP


_RENXIN_PET = 80         # 治愈兔, ability 200152 仁心 (generated catalog id)
_NAIHUO_PET = 553        # 刺轮砣, ability 200240 耐活王 (generated catalog id)
_NO_HEAL_PET = 1         # generic pet (ability_flags lacks heal-on-status)
_TARGET_PET = 100        # any non-leader basic pet for side_b's slot 0


def _seed_burn(state, side_id: int, slot: int, stacks: int):
    side_state = side(state, side_id)
    pet = side_state.pets[slot]
    pet = with_status(pet, StatusType.BURN, stacks)
    return replace_side(state, side_id, replace_pet(side_state, slot, pet))


def _seed_poison(state, side_id: int, slot: int, stacks: int):
    side_state = side(state, side_id)
    pet = side_state.pets[slot]
    pet = with_status(pet, StatusType.POISON, stacks)
    return replace_side(state, side_id, replace_pet(side_state, slot, pet))


def _wound(state, side_id: int, slot: int, missing: int):
    """Drop ``missing`` HP from the side_id/slot active pet (clamped >=1)."""
    side_state = side(state, side_id)
    pet = side_state.pets[slot]
    new_hp = max(1, pet.current_hp - missing)
    pet = pet._replace(current_hp=new_hp)
    return replace_side(state, side_id, replace_pet(side_state, slot, pet))


# ── 仁心 heal-on-burn (boundary 4a) ───────────────────────────────────────


def test_renxin_heals_on_enemy_burn():
    state = make_state((_RENXIN_PET, _NO_HEAL_PET), (_TARGET_PET, _NO_HEAL_PET))
    # Sanity: 仁心 carrier should carry HEAL_ON_BURN_DAMAGE after build.
    actor = state.side_a.pets[0]
    assert actor.ability_flags & int(AbilityFlag.HEAL_ON_BURN_DAMAGE), (
        f"pet {_RENXIN_PET} expected to carry HEAL_ON_BURN_DAMAGE; got "
        f"ability_flags=0x{actor.ability_flags:x}"
    )
    # Wound the actor so we can see a heal arrive.
    state = _wound(state, SIDE_A, 0, 200)
    state = _seed_burn(state, SIDE_B, 0, 3)

    actor_hp_before = state.side_a.pets[0].current_hp
    target_hp_before = state.side_b.pets[0].current_hp

    state = end_turn(state, skill_a_id=0, skill_b_id=0)

    actor_after = state.side_a.pets[0].current_hp
    target_after = state.side_b.pets[0].current_hp
    target_loss = target_hp_before - target_after
    actor_gain = actor_after - actor_hp_before
    assert target_loss > 0, "BURN should have ticked damage on side_b"
    assert actor_gain == target_loss, (
        f"actor gain ({actor_gain}) should equal target burn damage ({target_loss})"
    )


# ── 耐活王 heal-on-poison (boundary 4b) ───────────────────────────────────


def test_naihuowang_heals_on_enemy_poison():
    state = make_state((_NAIHUO_PET, _NO_HEAL_PET), (_TARGET_PET, _NO_HEAL_PET))
    actor = state.side_a.pets[0]
    assert actor.ability_flags & int(AbilityFlag.HEAL_ON_POISON_DAMAGE), (
        f"pet {_NAIHUO_PET} expected to carry HEAL_ON_POISON_DAMAGE; got "
        f"ability_flags=0x{actor.ability_flags:x}"
    )
    state = _wound(state, SIDE_A, 0, 200)
    state = _seed_poison(state, SIDE_B, 0, 4)

    actor_hp_before = state.side_a.pets[0].current_hp
    target_hp_before = state.side_b.pets[0].current_hp

    state = end_turn(state, skill_a_id=0, skill_b_id=0)

    actor_after = state.side_a.pets[0].current_hp
    target_after = state.side_b.pets[0].current_hp
    target_loss = target_hp_before - target_after
    actor_gain = actor_after - actor_hp_before
    assert target_loss > 0, "POISON should have ticked damage on side_b"
    assert actor_gain == target_loss


# ── negative: no flag → no heal ───────────────────────────────────────────


def test_no_heal_when_flag_missing():
    """A side_a active pet without HEAL_ON_BURN_DAMAGE must not heal."""
    state = make_state((_NO_HEAL_PET, _RENXIN_PET), (_TARGET_PET, _NO_HEAL_PET))
    actor = state.side_a.pets[0]
    assert not (actor.ability_flags & int(AbilityFlag.HEAL_ON_BURN_DAMAGE))
    state = _wound(state, SIDE_A, 0, 100)
    state = _seed_burn(state, SIDE_B, 0, 3)

    actor_hp_before = state.side_a.pets[0].current_hp
    target_hp_before = state.side_b.pets[0].current_hp

    state = end_turn(state, skill_a_id=0, skill_b_id=0)

    target_after = state.side_b.pets[0].current_hp
    assert target_hp_before - target_after > 0, "BURN should still tick on side_b"
    # Critical: actor HP must not increase.
    assert state.side_a.pets[0].current_hp == actor_hp_before


# ── heal capped at max HP ─────────────────────────────────────────────────


def test_heal_capped_at_max_hp():
    """When ``current_hp = max_hp - 1`` and enemy burn damage is large, the
    heal must clamp to ``max_hp`` rather than overflow.
    """
    state = make_state((_RENXIN_PET, _NO_HEAL_PET), (_TARGET_PET, _NO_HEAL_PET))
    actor = state.side_a.pets[0]
    assert actor.ability_flags & int(AbilityFlag.HEAL_ON_BURN_DAMAGE)
    max_hp = hot.PETS[actor.pet_id][STAT_HP]
    # Knock the actor down to max_hp - 1 so any heal that exceeds 1 must clamp.
    side_a = state.side_a
    pet = actor._replace(current_hp=max_hp - 1)
    state = replace_side(state, SIDE_A, replace_pet(side_a, 0, pet))
    # Stack high burn so a single tick deals more than 1.
    state = _seed_burn(state, SIDE_B, 0, 8)

    state = end_turn(state, skill_a_id=0, skill_b_id=0)

    actor_after = state.side_a.pets[0].current_hp
    assert actor_after == max_hp, (
        f"actor heal should clamp to max_hp={max_hp}, got {actor_after}"
    )
