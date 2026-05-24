"""Compiler-side BUFFBASE_CONF accessors built directly from pak source data."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from roco.common.buff_delta import (
    base_id_to_buff_delta as _base_id_to_buff_delta,
    pack_buff_delta_from_base_ids as _pack_buff_delta_from_base_ids,
    pack_buff_delta_from_buff_ids as _pack_buff_delta_from_buff_ids,
)
from roco.compiler_v2.static_artifacts.buffbase import build_buffbase_tables


@lru_cache(maxsize=1)
def _tables() -> dict[str, dict[int, Any]]:
    return build_buffbase_tables()


BUFFBASE_PARAMS: dict[int, tuple] = _tables()["params"]
BUFFBASE_ORDER: dict[int, int] = _tables()["order"]
BUFFBASE_TRIGGER_TYPE: dict[int, int] = _tables()["trigger"]


def base_id_to_buff_delta(base_id: int) -> int:
    return _base_id_to_buff_delta(base_id, BUFFBASE_ORDER, BUFFBASE_PARAMS)


def pack_buff_delta_from_base_ids(base_ids: list[int] | tuple[int, ...]) -> int:
    return _pack_buff_delta_from_base_ids(base_ids, BUFFBASE_ORDER, BUFFBASE_PARAMS)


def pack_buff_delta_from_buff_ids(
    buff_ids: list[int] | tuple[int, ...],
    buff_conf: dict[int, dict],
) -> int:
    return _pack_buff_delta_from_buff_ids(buff_ids, buff_conf, BUFFBASE_ORDER, BUFFBASE_PARAMS)
