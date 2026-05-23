"""Marker decorators that declare which pak axis a kernel op covers.

These decorators are **identity functions at runtime** — they do not
register handlers at import time, attach metadata to the wrapped
function, or otherwise touch state.  The compiler reads the decorator
*syntax* via AST (see :mod:`roco.compiler_v2.handler_axes`),
so all arguments must be plain literals (ints, strings, tuples, lists).

Three axes are recognised:

* :func:`handles_buff` — one or more ``Enum.BuffType`` symbols for
  which this op is the primary handler.  The compiler resolves symbols
  through generated Lua enum data before joining ``BUFFBASE_CONF``.
* :func:`handles_prefix` — one or more legacy ``buff_base_id // 1000``
  prefix buckets, expressed as the corresponding ``Enum.BuffType``
  symbol instead of a numeric prefix.
* :func:`handles_base_name` — exact ``BUFFBASE_CONF.editor_name`` anchors
  for outliers that are not covered by the order/prefix axes.

Each decorator accepts a list of ``(key, alias_or_note)`` tuples so a
single handler can advertise multi-key coverage with one decorator
invocation.  Stacking multiple decorators on the same function is
also fine — the compiler unions them.
"""

from __future__ import annotations

from typing import Callable, Sequence, TypeVar


F = TypeVar("F", bound=Callable[..., None])


def handles_buff(_entries: Sequence[tuple[str, str]]) -> Callable[[F], F]:
    """Declare that the decorated op handles these ``Enum.BuffType`` symbols.

    ``_entries`` is a list of ``("BFT_...", alias)`` tuples.  The
    alias is a short human-readable label (e.g. ``"STAT_MOD"``) used
    by ``PAK_PREFIX_NAMES`` and audit cross-references.  ``alias``
    must be a non-empty string literal so the compiler can pick it up
    via AST.
    """
    def _identity(func: F) -> F:
        return func
    return _identity


def handles_prefix(_entries: Sequence[tuple[str, str]]) -> Callable[[F], F]:
    """Declare that the decorated op covers legacy prefix buckets.

    ``_entries`` is a list of ``("BFT_...", alias)`` tuples.  The
    compiler derives ``prefix = 2000 + Enum.BuffType[symbol]``.  This
    keeps pak numbering in generated data while leaving the engine to
    state only the semantic family it implements.
    """
    def _identity(func: F) -> F:
        return func
    return _identity


def handles_base_name(_entries: Sequence[tuple[str, str]]) -> Callable[[F], F]:
    """Declare exact ``BUFFBASE_CONF.editor_name`` anchors handled by the op.

    ``_entries`` is a list of ``(editor_name, note)`` tuples.  The
    compiler resolves names to current pak base ids, so the engine does
    not own the numeric id.
    """
    def _identity(func: F) -> F:
        return func
    return _identity
