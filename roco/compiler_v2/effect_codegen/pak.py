"""Lazy loaders for the pak tables used during effect codegen."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_pak_table(path: Path) -> dict[int, dict[str, Any]]:
    """Load a pak BinData JSON table and return it keyed by integer id."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("RocoDataRows", data)
    if not isinstance(rows, dict):
        raise ValueError(f"unexpected table format: {path}")
    return {int(k): v for k, v in rows.items()}


class PakTables:
    """Lazy-loaded pak data tables needed for effect codegen."""

    def __init__(self, pak_data_dir: Path):
        self._dir = pak_data_dir / "BinData"
        self._effect_conf: dict[int, dict] | None = None
        self._buff_conf: dict[int, dict] | None = None
        self._skill_conf: dict[int, dict] | None = None

    @property
    def effect_conf(self) -> dict[int, dict]:
        if self._effect_conf is None:
            self._effect_conf = _load_pak_table(self._dir / "EFFECT_CONF.json")
        return self._effect_conf

    @property
    def buff_conf(self) -> dict[int, dict]:
        if self._buff_conf is None:
            self._buff_conf = _load_pak_table(self._dir / "BUFF_CONF.json")
        return self._buff_conf

    @property
    def skill_conf(self) -> dict[int, dict]:
        if self._skill_conf is None:
            self._skill_conf = _load_pak_table(self._dir / "SKILL_CONF.json")
        return self._skill_conf
