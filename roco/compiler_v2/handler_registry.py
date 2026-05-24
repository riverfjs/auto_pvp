"""Source loader for the stable engine handler registry."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "roco" / "compiler_v2" / "handler_registry.json"


def func_to_const(name: str) -> str:
    if name == "_noop":
        return "H_NOOP"
    if name.startswith("op_"):
        return "H_" + name[3:].upper()
    return "H_" + name.upper()


@lru_cache(maxsize=1)
def load_handler_order() -> tuple[str, ...]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    handlers = payload.get("handlers")
    if not isinstance(handlers, list) or not handlers:
        raise RuntimeError(f"{REGISTRY_PATH} has no handlers list")
    return tuple(str(name) for name in handlers)


@lru_cache(maxsize=1)
def load_handler_indices() -> dict[str, int]:
    return {
        func_to_const(name): idx
        for idx, name in enumerate(load_handler_order())
    }


class _HandlerIndices:
    def __getattr__(self, name: str) -> int:
        indices = load_handler_indices()
        try:
            return indices[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


handler_indices = _HandlerIndices()


def __getattr__(name: str) -> Any:
    if name.startswith("H_"):
        return getattr(handler_indices, name)
    raise AttributeError(name)
