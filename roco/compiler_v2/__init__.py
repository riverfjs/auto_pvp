"""Experimental static compiler pipeline.

This package backs the formal compiler artifact path.  It reads pak
BinData and Lua enum sources, then writes Python static artifacts without
using JSONL rule files as semantic inputs.
"""

from __future__ import annotations

__all__ = [
    "build",
    "emit",
    "sources",
]
