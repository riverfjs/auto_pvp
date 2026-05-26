from __future__ import annotations

import pytest

from roco.common.primitive_keys import buff_ref_key
from roco.compiler_v2.timing_keys import pak_cast_moment_key
from roco.engine.artifacts.linked_op import LinkGapError, LinkedOp
from roco.engine.artifacts.primitive_linker import link_primitive_rows
from roco.engine.kernel.core.ctx import StageCtx
from roco.engine.kernel.ops.skill import op_power_bps_by_target_meteor_mark


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


def test_bft_target_has_buff_desc_only_sentinels_stay_gap():
    for buff_id in (20630120, 20630160, 20630180, 20630190, 20630200):
        with pytest.raises(LinkGapError, match="target_has_buff_desc_sentinel_unresolved"):
            _link(buff_id)


def test_bft_target_has_buff_sequence_sentinels_stay_gap():
    with pytest.raises(LinkGapError, match="target_has_buff_sequence_sentinel_unsupported"):
        _link(20630060)


def test_bft_target_has_buff_mark_total_to_meteor_stays_gap():
    for buff_id in (20630040, 20630050):
        with pytest.raises(LinkGapError, match="target_has_buff_mark_total_to_meteor_desc_unresolved"):
            _link(buff_id)


def test_target_has_buff_runtime_meteor_power_uses_explicit_special_effect():
    ctx = StageCtx()
    ctx.skill_dam_type = 8
    ctx.target_meteor_mark_stacks = 2
    op_power_bps_by_target_meteor_mark(ctx, (0, 11, 1, 0, 0, 8, 2000, 0, 0))
    assert ctx.power_bps == 14000
