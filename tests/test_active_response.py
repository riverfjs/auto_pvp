"""Pak BFT_CAST_SKILL_AFTER_ATTACK active-response runtime coverage."""

from __future__ import annotations

from roco.common.enums import SkillCategory, StatusType
from roco.common.packing import MarkIdx, _unpack_mark
from roco.common.primitive_keys import buff_ref_key
from roco.compiler_v2.timing_keys import pak_cast_moment_key
from roco.engine.artifacts.primitive_linker import link_primitive_row
from roco.engine.common.choices import SIDE_A, SIDE_B
from roco.engine.kernel.active_buffs import active_buff_duration, active_buff_id, pack_active_buff
from roco.engine.kernel.active_response import (
    after_attack_response_supported,
    trigger_after_attack_active_buffs,
)
from roco.engine.kernel.ctx import StageCtx
from roco.engine.kernel.op_mods.buffs import op_apply_active_buff
from roco.engine.kernel.residual.after_move import apply_after_move
from roco.engine.kernel.state import make_state, replace_pet, replace_side, side, status_stack


def _seed_active_response(state, side_id: int, slot: int, buff_id: int, duration: int = 1):
    side_state = side(state, side_id)
    pet = side_state.pets[slot]
    lane = pack_active_buff(buff_id, side_id, slot, duration)
    return replace_side(state, side_id, replace_pet(side_state, slot, pet._replace(active_buffs=lane)))


def test_bft_cast_skill_after_attack_links_to_active_buff_install():
    row = (buff_ref_key(20190050), pak_cast_moment_key(7), 1, 10000, 0, 0, 0, 0)
    linked = link_primitive_row(row, source_name="应对攻击灼烧")
    assert linked.op_name == "op_apply_active_buff"
    assert linked.runtime_args() == (20190050, 2, 1, 99)


def test_round_reduce_active_buff_install_gets_duration():
    state = make_state((1, 2, 3), (4, 5, 6))
    ctx = StageCtx()
    ctx.reset(SIDE_A, 0, SIDE_B, 0, 0)
    op_apply_active_buff(ctx, (0, 7, 1, 10000, 0, 20190050, 2, 1, 99))
    new_state = apply_after_move(state, SIDE_A, 0, SIDE_B, 0, ctx)
    lane = side(new_state, SIDE_A).pets[0].active_buffs
    assert active_buff_id(lane) == 20190050
    assert active_buff_duration(lane) == 1


def test_after_attack_active_response_applies_burn_to_attacker():
    assert after_attack_response_supported(20190050)
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_response(state, SIDE_B, 0, 20190050)
    new_state = trigger_after_attack_active_buffs(
        state,
        SIDE_A,
        0,
        SIDE_B,
        0,
        SkillCategory.PHYSICAL.value,
        damage_dealt=10,
    )
    assert status_stack(side(new_state, SIDE_A).pets[0], StatusType.BURN) == 1


def test_after_attack_active_response_applies_meteor_marks_to_attacker_side():
    assert after_attack_response_supported(20190260)
    state = make_state((1, 2, 3), (4, 5, 6))
    state = _seed_active_response(state, SIDE_B, 0, 20190260)
    new_state = trigger_after_attack_active_buffs(
        state,
        SIDE_A,
        0,
        SIDE_B,
        0,
        SkillCategory.MAGICAL.value,
        damage_dealt=10,
    )
    assert _unpack_mark(side(new_state, SIDE_A).marks, MarkIdx.METEOR) == 2
