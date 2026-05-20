"""Marker decorators that declare which pak axis a kernel op covers.

These decorators are **identity functions at runtime** — they do not
register handlers at import time, attach metadata to the wrapped
function, or otherwise touch state.  The compiler reads the decorator
*syntax* via AST (see :mod:`roco.compiler.codegen.handler_collector`),
so all arguments must be plain literals (ints, strings, tuples, lists).

Three axes are recognised:

* :func:`handles_buff` — one or more ``BUFFBASE_CONF.buffbase_order``
  values for which this op is the primary handler.  The proto axis
  introduced in 7C, now self-described on the handler itself instead
  of in ``buffbase_order_handlers.jsonl``.
* :func:`handles_prefix` — one or more legacy ``buff_base_id // 1000``
  prefix buckets.  Only the three mixed prefixes (2011, 2046, 2050)
  whose buffbase_order distribution is not 100% concentrated survive
  on this axis.
* :func:`handles_base_id` — exact ``buff_base_id`` overrides.  Used
  for the eight hand-curated mark / status base anchors that fall
  outside both other axes.

Each decorator accepts a list of ``(key, alias_or_note)`` tuples so a
single handler can advertise multi-key coverage with one decorator
invocation.  Stacking multiple decorators on the same function is
also fine — the compiler unions them.
"""

from __future__ import annotations

from typing import Callable, Sequence, TypeVar


F = TypeVar("F", bound=Callable[..., None])


def handles_buff(_entries: Sequence[tuple[int, str]]) -> Callable[[F], F]:
    """Declare that the decorated op handles these ``buffbase_order`` values.

    ``_entries`` is a list of ``(buffbase_order, alias)`` tuples.  The
    alias is a short human-readable label (e.g. ``"STAT_MOD"``) used
    by ``PAK_PREFIX_NAMES`` and audit cross-references.  ``alias``
    must be a non-empty string literal so the compiler can pick it up
    via AST.
    """
    def _identity(func: F) -> F:
        return func
    return _identity


def handles_prefix(_entries: Sequence[tuple[int, str]]) -> Callable[[F], F]:
    """Declare that the decorated op covers legacy prefix buckets.

    ``_entries`` is a list of ``(prefix, alias)`` tuples where
    ``prefix = buff_base_id // 1000``.  Reserved for the three mixed
    prefixes whose buffbase_order distribution prevents migration to
    :func:`handles_buff`.
    """
    def _identity(func: F) -> F:
        return func
    return _identity


def handles_base_id(_entries: Sequence[tuple[int, str]]) -> Callable[[F], F]:
    """Declare exact ``buff_base_id`` overrides handled by the op.

    ``_entries`` is a list of ``(base_id, note)`` tuples.  ``note`` is
    free-form documentation describing why the base id is anchored
    here instead of going through the structural axes.
    """
    def _identity(func: F) -> F:
        return func
    return _identity
