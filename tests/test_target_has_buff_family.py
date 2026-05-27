from __future__ import annotations

import pytest

from roco.common.primitive_keys import buff_ref_key
from roco.compiler_v2.timing_keys import pak_cast_moment_key
from roco.engine.artifacts.linked_op import LinkGapError, LinkedOp
from roco.engine.artifacts.primitive_linker import link_primitive_rows
from roco.engine.kernel.core.ctx import StageCtx
from roco.common.constants import BLOODLINE_LEADER, BLOODLINE_POLLUTANT
from roco.engine.kernel.ops.skill import (
    op_power_bps_by_target_meteor_mark,
    op_power_bps_by_target_skill_total_cost,
    op_power_bps_if_target_bloodline,
    op_power_flat_by_target_skill_type_count,
)


def _link(buff_id: int):
    return link_primitive_rows(
        (buff_ref_key(buff_id), pak_cast_moment_key(11), 1, 10000, 0, 0, 0, 0),
        source_name=str(buff_id),
    )


def test_bft_target_has_buff_starfall_power_dedupes_pak_mark_variants():
    assert _link(20630100) == (
        LinkedOp("op_power_bps_by_target_meteor_mark", 11, 1, 10000, 8, 2000, 0, 0),
    )
    assert _link(20630130) == (
        LinkedOp("op_power_bps_by_target_meteor_mark", 11, 1, 10000, 0, 2000, 0, 0),
    )


def test_bft_target_has_buff_desc_derived_sentinels_bind_by_exact_pak_shape():
    assert _link(20630120) == (
        LinkedOp("op_power_flat_by_target_skill_type_count", 11, 1, 10000, 10, 0, 0, 0),
    )
    assert _link(20630190) == (
        LinkedOp("op_power_bps_by_target_skill_total_cost", 11, 1, 10000, 1000, 0, 0, 0),
    )
    assert _link(20630160) == (
        LinkedOp("op_power_bps_if_target_bloodline", 11, 1, 10000, 1, 10000, 0, 0),
    )
    assert _link(20630200) == (
        LinkedOp("op_power_bps_if_target_bloodline", 11, 1, 10000, 2, 10000, 0, 0),
    )
    assert _link(20630180) == (
        LinkedOp("op_power_bps_if_target_bloodline", 11, 1, 10000, 3, 10000, 0, 0),
    )


def test_bft_target_has_buff_sequence_sentinels_stay_gap():
    with pytest.raises(LinkGapError, match="target_has_buff_sequence_sentinel_unsupported"):
        _link(20630060)


def test_bft_target_has_buff_mark_total_to_meteor_links_from_pak_mark_refs():
    for buff_id in (20630040, 20630050):
        assert _link(buff_id) == (
            LinkedOp("op_meteor_mark_by_target_mark_total", 11, 1, 10000, 1, 0, 0, 0),
        )


def test_target_has_buff_runtime_meteor_power_uses_explicit_special_effect():
    ctx = StageCtx()
    ctx.skill_dam_type = 8
    ctx.target_meteor_mark_stacks = 2
    op_power_bps_by_target_meteor_mark(ctx, (0, 11, 1, 0, 0, 8, 2000, 0, 0))
    assert ctx.power_bps == 14000


def test_target_has_buff_runtime_derived_observations():
    ctx = StageCtx()
    ctx.target_equipped_skill_type_count = 3
    ctx.target_equipped_skill_total_cost = 4
    op_power_flat_by_target_skill_type_count(ctx, (0, 11, 1, 0, 0, 10, 0, 0, 0))
    assert ctx.power == 30
    op_power_bps_by_target_skill_total_cost(ctx, (0, 11, 1, 0, 0, 1000, 0, 0, 0))
    assert ctx.power_bps == 14000


def test_target_has_buff_runtime_bloodline_conditions():
    ctx = StageCtx()
    ctx.target_bloodline = BLOODLINE_LEADER
    op_power_bps_if_target_bloodline(ctx, (0, 11, 1, 0, 0, 1, 10000, 0, 0))
    assert ctx.power_bps == 20000

    ctx = StageCtx()
    ctx.target_bloodline = BLOODLINE_POLLUTANT
    op_power_bps_if_target_bloodline(ctx, (0, 11, 1, 0, 0, 2, 10000, 0, 0))
    assert ctx.power_bps == 20000

    ctx = StageCtx()
    ctx.target_primary = 0
    ctx.target_secondary = -1
    ctx.target_bloodline = 2
    op_power_bps_if_target_bloodline(ctx, (0, 11, 1, 0, 0, 3, 10000, 0, 0))
    assert ctx.power_bps == 20000
