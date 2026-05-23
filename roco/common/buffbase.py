"""Helpers that adapt generated BUFFBASE_CONF params to kernel buff deltas."""

from __future__ import annotations

from roco.common.packing import (
    BUFF_ATK_MAG,
    BUFF_ATK_PHYS,
    BUFF_DEF_MAG,
    BUFF_DEF_PHYS,
    BUFF_SPEED,
    _add_buff_bps,
    _buff_lane,
)
from roco.generated.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS

_STAT_TO_BUFF_LANE: dict[int, tuple[int, int]] = {
    29: (BUFF_ATK_PHYS, 1),
    30: (BUFF_ATK_MAG, 1),
    31: (BUFF_DEF_PHYS, 1),
    32: (BUFF_DEF_MAG, 1),
    33: (BUFF_ATK_PHYS, -1),
    34: (BUFF_ATK_MAG, -1),
    35: (BUFF_DEF_PHYS, -1),
    36: (BUFF_DEF_MAG, -1),
}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _normalise_bps(raw: int) -> int:
    if abs(raw) >= 100:
        return raw
    return raw * 100


def base_id_to_buff_delta(base_id: int) -> int:
    """Return the packed stat delta for a BUFFBASE_CONF stat row.

    Only ``buffbase_order=1`` rows are stat deltas.  Unsupported base rows
    return zero so callers can keep non-stat semantics out of stat lanes.
    """
    if BUFFBASE_ORDER.get(base_id) != 1:
        return 0
    params = BUFFBASE_PARAMS.get(base_id) or ()
    if len(params) < 3:
        return 0
    stat_code = _as_int(params[0])
    raw = _normalise_bps(_as_int(params[2]))
    if raw == 0:
        return 0
    if stat_code == 6:
        return _add_buff_bps(0, BUFF_SPEED, raw)
    lane = _STAT_TO_BUFF_LANE.get(stat_code)
    if lane is None:
        return 0
    idx, sign = lane
    return _add_buff_bps(0, idx, sign * abs(raw))


def pack_buff_delta_from_base_ids(base_ids: list[int] | tuple[int, ...]) -> int:
    packed = 0
    for base_id in base_ids:
        packed = merge_buff_delta(packed, base_id_to_buff_delta(int(base_id)))
    return packed


def pack_buff_delta_from_buff_ids(
    buff_ids: list[int] | tuple[int, ...],
    buff_conf: dict[int, dict],
) -> int:
    packed = 0
    for buff_id in buff_ids:
        rec = buff_conf.get(int(buff_id)) or {}
        packed = merge_buff_delta(
            packed,
            pack_buff_delta_from_base_ids(tuple(int(v) for v in rec.get("buff_base_ids") or () if v)),
        )
    return packed


def merge_buff_delta(packed: int, delta: int) -> int:
    for idx in range(7):
        up, down = _buff_lane(delta, idx)
        if up:
            packed = _add_buff_bps(packed, idx, up)
        if down:
            packed = _add_buff_bps(packed, idx, -down)
    return packed


def scale_buff_delta(delta: int, count: int) -> int:
    if count <= 0 or delta == 0:
        return 0
    packed = 0
    for _ in range(count):
        packed = merge_buff_delta(packed, delta)
    return packed


def pack_buff_delta_from_row(row: tuple[int, ...], start: int, end: int) -> int:
    """Decode either packed-delta rows or legacy base-id argument rows."""
    args = tuple(int(row[idx]) for idx in range(start, end) if int(row[idx]))
    if not args:
        return 0
    if any(arg in BUFFBASE_PARAMS for arg in args):
        return pack_buff_delta_from_base_ids(args)
    return args[0]
