"""Compiler-side BUFFBASE_CONF accessors built directly from pak source data."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from roco.compiler_v2.static_artifacts.buffbase import build_buffbase_tables


@lru_cache(maxsize=1)
def _tables() -> dict[str, dict[int, Any]]:
    return build_buffbase_tables()


BUFFBASE_PARAMS: dict[int, tuple] = _tables()["params"]
BUFFBASE_ORDER: dict[int, int] = _tables()["order"]
BUFFBASE_TRIGGER_TYPE: dict[int, int] = _tables()["trigger"]
