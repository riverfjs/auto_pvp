"""Marker decorators that declare which pak axis a kernel op covers.

These decorators attach local engine metadata to op functions.  They do not
register handlers at import time or touch global state.  The engine linker uses
the metadata to bind pak-derived primitive keys to runtime handlers.

Three axes are recognised:

* :func:`handles_buff` — one or more ``Enum.BuffType`` symbols for
  which this op is the primary handler.
* :func:`handles_prefix` — one or more mixed ``buff_base_id // 1000``
  prefix buckets, expressed as the corresponding ``Enum.BuffType``
  symbol instead of a numeric prefix.
* :func:`handles_mark` — one or more ``DESC_NOTE_CONF.note`` values for
  mark primitives whose exact ``BUFF_CONF.name`` must route before generic
  buffbase dispatch.
Exact outliers are generated from pak structures such as
``BUFF_CONF`` names, types, params, and ``SKILL_CONF.skill_result`` chains.
The engine should not anchor handlers to pak display names except for
``handles_mark``: mark lane behavior is concrete engine logic, while
``DESC_NOTE_CONF.note`` is the pak-owned stable name the compiler verifies.

Each decorator accepts a list of ``(key, alias_or_note)`` tuples so a
single handler can advertise multi-key coverage with one decorator
invocation.  Stacking multiple decorators on the same function is
also fine.
"""

from __future__ import annotations

from typing import Callable, Sequence, TypeVar


F = TypeVar("F", bound=Callable[..., None])

HANDLES_BUFF_ATTR = "__roco_handles_buff__"
HANDLES_MARK_ATTR = "__roco_handles_mark__"
HANDLES_PREFIX_ATTR = "__roco_handles_prefix__"


def _append_entries(func: F, attr: str, entries: Sequence[tuple[str, str]]) -> F:
    existing = tuple(getattr(func, attr, ()))
    setattr(func, attr, existing + tuple(entries))
    return func


def handles_buff(_entries: Sequence[tuple[str, str]]) -> Callable[[F], F]:
    """Declare that the decorated op handles these ``Enum.BuffType`` symbols.

    ``_entries`` is a list of ``("BFT_...", alias)`` tuples.  The
    alias is a short human-readable label (e.g. ``"STAT_MOD"``) used
    by ``PAK_PREFIX_NAMES`` and audit cross-references.
    """
    def _decorate(func: F) -> F:
        return _append_entries(func, HANDLES_BUFF_ATTR, _entries)
    return _decorate


def handles_prefix(_entries: Sequence[tuple[str, str]]) -> Callable[[F], F]:
    """Declare that the decorated op covers mixed prefix buckets.

    ``_entries`` is a list of ``("BFT_...", alias)`` tuples.  The
    primitive-axis generation derives ``prefix = 2000 + Enum.BuffType[symbol]``.
    """
    def _decorate(func: F) -> F:
        return _append_entries(func, HANDLES_PREFIX_ATTR, _entries)
    return _decorate


def handles_mark(_entries: Sequence[tuple[str, str]]) -> Callable[[F], F]:
    """Declare that the decorated op handles these pak mark note names.

    ``_entries`` is a list of ``("DESC_NOTE_CONF.note", "MARK_IDX_NAME")``
    tuples.  The compiler verifies the note against generated pak data and
    uses the second value only to join the handler to the packed runtime mark
    lane.
    """
    def _decorate(func: F) -> F:
        return _append_entries(func, HANDLES_MARK_ATTR, _entries)
    return _decorate
