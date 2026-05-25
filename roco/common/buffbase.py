"""Runtime adapters for generated BUFFBASE_CONF params."""

from __future__ import annotations

from roco.common.buff_delta import (
    base_id_to_buff_delta as _base_id_to_buff_delta,
    merge_buff_delta,
    pack_buff_delta_from_base_ids as _pack_buff_delta_from_base_ids,
    pack_buff_delta_from_buff_ids as _pack_buff_delta_from_buff_ids,
    pack_buff_delta_from_row as _pack_buff_delta_from_row,
    scale_buff_delta,
)
from roco.generated.pak.buffbase_params import BUFFBASE_ORDER, BUFFBASE_PARAMS


def base_id_to_buff_delta(base_id: int) -> int:
    return _base_id_to_buff_delta(base_id, BUFFBASE_ORDER, BUFFBASE_PARAMS)


def pack_buff_delta_from_base_ids(base_ids: list[int] | tuple[int, ...]) -> int:
    return _pack_buff_delta_from_base_ids(base_ids, BUFFBASE_ORDER, BUFFBASE_PARAMS)


def pack_buff_delta_from_buff_ids(
    buff_ids: list[int] | tuple[int, ...],
    buff_conf: dict[int, dict],
) -> int:
    return _pack_buff_delta_from_buff_ids(buff_ids, buff_conf, BUFFBASE_ORDER, BUFFBASE_PARAMS)


def pack_buff_delta_from_row(row: tuple[int, ...], start: int, end: int) -> int:
    return _pack_buff_delta_from_row(row, start, end, BUFFBASE_PARAMS, BUFFBASE_ORDER)
