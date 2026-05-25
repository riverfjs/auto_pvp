"""Marker decorators that declare which pak axis a kernel op covers.

These decorators attach local engine metadata to op functions.  They do not
register handlers at import time or touch global state.  The engine linker uses
the metadata to bind pak-derived primitive keys to runtime handlers.

Two axes are recognised:

* :func:`handles_buff` — one or more ``Enum.BuffType`` symbols for
  which this op is the primary handler.
* :func:`handles_prefix` — one or more mixed ``buff_base_id // 1000``
  prefix buckets, expressed as the corresponding ``Enum.BuffType``
  symbol instead of a numeric prefix.
Exact outliers are linked from pak ids/params by the artifact linker.  The
decorators only publish pak enum symbols; they do not carry engine labels.
"""

from __future__ import annotations

from typing import Callable, Sequence, TypeVar


F = TypeVar("F", bound=Callable[..., None])

HANDLES_BUFF_ATTR = "__roco_handles_buff__"
HANDLES_PREFIX_ATTR = "__roco_handles_prefix__"


def _append_entries(func: F, attr: str, entries: Sequence[str]) -> F:
    existing = tuple(getattr(func, attr, ()))
    setattr(func, attr, existing + tuple(str(entry) for entry in entries))
    return func


def handles_buff(_entries: Sequence[str]) -> Callable[[F], F]:
    """Declare that the decorated op handles these ``Enum.BuffType`` symbols.
    """
    def _decorate(func: F) -> F:
        return _append_entries(func, HANDLES_BUFF_ATTR, _entries)
    return _decorate


def handles_prefix(_entries: Sequence[str]) -> Callable[[F], F]:
    """Declare that the decorated op covers mixed prefix buckets.

    The primitive-axis generation derives ``prefix = 2000 +
    Enum.BuffType[symbol]``.
    """
    def _decorate(func: F) -> F:
        return _append_entries(func, HANDLES_PREFIX_ATTR, _entries)
    return _decorate
