"""Pak counter-trigger family (1031xxx) install-and-consume coverage."""

from __future__ import annotations

from roco.engine.common.choices import SIDE_A, SIDE_B, move_choice
from roco.engine.kernel.mechanics import update
from roco.engine.kernel.state import make_state
from roco.generated import catalog_debug as debug
from roco.generated import catalog_hot as hot
from roco.generated.counter_skill_table import COUNTER_SKILL_TABLE


def _pet_id(name: str) -> int:
    return debug.PET_IDS_BY_NAME[name]


def _skill_id(name: str) -> int:
    return debug.SKILL_IDS_BY_NAME[name]


def test_counter_install_arms_side_state_after_defensive_skill():
    """防御 (pak 7020780) → effect 1031047 → H_INSTALL_COUNTER stages 7020781.

    After the defender plays 防御 (a defense-category skill that deals no
    damage) and the attacker focuses (no incoming hit to consume the
    counter), ``apply_after_move`` folds ``ctx.actor_counter_install_skill_id``
    into ``SideState.counter_skill_id`` and the slot stays armed for
    later hits.
    """
    fang_yu = _skill_id("防御")
    defender = _pet_id("水蓝蓝")
    attacker = _pet_id("火花")

    state = make_state(
        (attacker,),
        (defender,),
        team_a_moves=((0,),),  # attacker has no skill → focus
        team_b_moves=((fang_yu,),),
        rng_seed=1,
    )
    # Defender's pet has 防御 in slot 0; just confirm catalog wiring matches.
    assert hot.PET_SKILLS[defender][0] == fang_yu

    result = update(state, move_choice(0), move_choice(0))
    # Attacker did nothing → counter stays armed with the 应对！防御 id.
    assert result.state.side_b.counter_skill_id == 7020781


def test_counter_consume_zero_power_still_clears_slot():
    """One-shot semantics: counter slot clears even if the response skill is power=0.

    Arm 应对！防御 (7020781, power=0) and confirm the slot zeroes after the
    incoming hit lands, even though no counter damage rebounds.
    """
    slap = _skill_id("拍击")
    defender = _pet_id("水蓝蓝")
    attacker = _pet_id("火花")
    counter_skill_id = 7020781  # 应对！防御 — magical, element=普通, power=0
    assert counter_skill_id in COUNTER_SKILL_TABLE
    assert COUNTER_SKILL_TABLE[counter_skill_id][0] == 0  # power=0

    state = make_state(
        (attacker,),
        (defender,),
        team_a_moves=((slap,),),
        team_b_moves=((0,),),  # defender will focus (no skill)
        rng_seed=1,
    )
    state = state._replace(side_b=state.side_b._replace(counter_skill_id=counter_skill_id))
    attacker_hp_before = state.side_a.pets[0].current_hp

    result = update(state, move_choice(0), move_choice(0))
    # Slot cleared whether or not damage rebounded.
    assert result.state.side_b.counter_skill_id == 0
    # Power=0 → no counter damage to attacker.
    assert result.state.side_a.pets[0].current_hp == attacker_hp_before


def test_counter_consume_with_powered_response_skill_damages_attacker():
    """Use a counter skill that does carry power so we observe attacker HP drop."""
    slap = _skill_id("拍击")
    defender = _pet_id("水蓝蓝")
    attacker = _pet_id("火花")
    # 7020451 应对！突袭 — power=210, physical, element=普通; high enough
    # to land non-trivial damage on the attacker.
    counter_skill_id = 7020451
    assert COUNTER_SKILL_TABLE[counter_skill_id][0] > 0

    state = make_state(
        (attacker,),
        (defender,),
        team_a_moves=((slap,),),
        team_b_moves=((0,),),
        rng_seed=1,
    )
    state = state._replace(side_b=state.side_b._replace(counter_skill_id=counter_skill_id))
    attacker_hp_before = state.side_a.pets[0].current_hp

    result = update(state, move_choice(0), move_choice(0))

    assert result.state.side_b.counter_skill_id == 0  # cleared after firing
    expected_loss = result.damage_a  # damage taken from own attack only
    assert result.state.side_a.pets[0].current_hp < attacker_hp_before - expected_loss


def test_counter_does_not_fire_when_no_skill_armed():
    """Sanity: without an armed counter, no damage rebounds onto the attacker."""
    slap = _skill_id("拍击")
    defender = _pet_id("水蓝蓝")
    attacker = _pet_id("火花")

    state = make_state(
        (attacker,),
        (defender,),
        team_a_moves=((slap,),),
        team_b_moves=((0,),),
        rng_seed=1,
    )
    attacker_hp_before = state.side_a.pets[0].current_hp

    result = update(state, move_choice(0), move_choice(0))

    assert result.state.side_b.counter_skill_id == 0
    assert result.state.side_a.pets[0].current_hp == attacker_hp_before  # untouched
