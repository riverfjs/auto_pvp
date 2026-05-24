"""Pure BUFFBASE_CONF stat-delta packing helpers."""

from __future__ import annotations

BUFF_UNIT_BPS = 100
BUFF_LANE_BITS = 8
BUFF_LANE_MASK = (1 << BUFF_LANE_BITS) - 1
BUFF_STAT_BITS = BUFF_LANE_BITS * 2
BUFF_ATK_PHYS = 0
BUFF_ATK_MAG = 1
BUFF_DEF_MAG = 3
BUFF_DEF_PHYS = 2
BUFF_SPEED = 4


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


def base_id_to_buff_delta(
    base_id: int,
    buffbase_order: dict[int, int],
    buffbase_params: dict[int, tuple],
) -> int:
    """Return the packed stat delta for a BUFFBASE_CONF stat row."""

    if buffbase_order.get(base_id) != 1:
        return 0
    params = buffbase_params.get(base_id) or ()
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


def pack_buff_delta_from_base_ids(
    base_ids: list[int] | tuple[int, ...],
    buffbase_order: dict[int, int],
    buffbase_params: dict[int, tuple],
) -> int:
    packed = 0
    for base_id in base_ids:
        packed = merge_buff_delta(
            packed,
            base_id_to_buff_delta(int(base_id), buffbase_order, buffbase_params),
        )
    return packed


def pack_buff_delta_from_buff_ids(
    buff_ids: list[int] | tuple[int, ...],
    buff_conf: dict[int, dict],
    buffbase_order: dict[int, int],
    buffbase_params: dict[int, tuple],
) -> int:
    packed = 0
    for buff_id in buff_ids:
        rec = buff_conf.get(int(buff_id)) or {}
        packed = merge_buff_delta(
            packed,
            pack_buff_delta_from_base_ids(
                tuple(int(v) for v in rec.get("buff_base_ids") or () if v),
                buffbase_order,
                buffbase_params,
            ),
        )
    return packed


def pack_buff_delta_from_row(
    row: tuple[int, ...],
    start: int,
    end: int,
    buffbase_params: dict[int, tuple],
    buffbase_order: dict[int, int],
) -> int:
    """Decode either packed-delta rows or base-id argument rows."""

    args = tuple(int(row[idx]) for idx in range(start, end) if int(row[idx]))
    if not args:
        return 0
    if any(arg in buffbase_params for arg in args):
        return pack_buff_delta_from_base_ids(args, buffbase_order, buffbase_params)
    return args[0]


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


def _buff_lane(packed: int, idx: int) -> tuple[int, int]:
    shift = idx * BUFF_STAT_BITS
    up = (packed >> shift) & BUFF_LANE_MASK
    down = (packed >> (shift + BUFF_LANE_BITS)) & BUFF_LANE_MASK
    return up * BUFF_UNIT_BPS, down * BUFF_UNIT_BPS


def _add_buff_bps(packed: int, idx: int, delta_bps: int) -> int:
    shift = idx * BUFF_STAT_BITS
    up_units = (packed >> shift) & BUFF_LANE_MASK
    down_units = (packed >> (shift + BUFF_LANE_BITS)) & BUFF_LANE_MASK
    units = min(BUFF_LANE_MASK, abs(int(delta_bps)) // BUFF_UNIT_BPS)
    if delta_bps >= 0:
        up_units = min(BUFF_LANE_MASK, up_units + units)
    else:
        down_units = min(BUFF_LANE_MASK, down_units + units)
    packed &= ~(0xFFFF << shift)
    return packed | (up_units << shift) | (down_units << (shift + BUFF_LANE_BITS))


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _normalise_bps(raw: int) -> int:
    if abs(raw) >= 100:
        return raw
    return raw * 100
