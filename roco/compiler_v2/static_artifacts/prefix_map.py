from __future__ import annotations

import json

from roco.compiler_v2.model import StaticBundle
from roco.compiler_v2.primitive_map_builder import build_primitive_map

from .common import PRIMITIVE_MAP_PATH


def write_primitive_map(bundle: StaticBundle) -> dict:
    result = build_primitive_map(bundle)
    serializable = {
        key: value
        for key, value in result.items()
        if key not in {"prefix_aliases", "primitive_axes"}
    }
    PRIMITIVE_MAP_PATH.write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result
