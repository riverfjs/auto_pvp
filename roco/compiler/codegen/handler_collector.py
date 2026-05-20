"""AST scanner that collects ``@handles_*`` decorator metadata.

Companion to :mod:`roco.compiler.codegen.handlers` (which discovers
``op_*`` function *names* via AST).  This module reads the
*decorators* on those same functions and produces three lookup tables
that replace the historical hand-edited JSONLs:

* ``buffbase_order_map`` — ``{buffbase_order: (handler_name, alias)}``;
  the post-7C primary axis, previously in
  ``rules/buffbase_order_handlers.jsonl``.
* ``prefix_map`` — ``{prefix: (handler_name, alias)}``; legacy mixed-
  prefix overrides, previously the ``prefix`` rows in
  ``rules/prefix_handlers.jsonl``.
* ``base_id_map`` — ``{base_id: (handler_name, note)}``; exact base_id
  anchors, previously the ``base_id`` rows in
  ``rules/prefix_handlers.jsonl``.

AST-only: no import side effects, no decorator runtime cost.  Every
argument the decorator carries must be a literal so
:func:`ast.literal_eval` can read it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]

# Modules scanned for ``op_*`` handlers + their decorators.  Kept in
# sync with the registry in :mod:`roco.compiler.codegen.handlers`; if
# a new op_mod module is added there it must be added here too.
_OP_MODULES: tuple[str, ...] = (
    "roco.engine.kernel.op_mods.damage",
    "roco.engine.kernel.op_mods.buffs",
    "roco.engine.kernel.op_mods.skill",
    "roco.engine.kernel.op_mods.combat",
    "roco.engine.kernel.op_resources",
    "roco.engine.kernel.op_marks",
    "roco.engine.kernel.op_status",
    "roco.engine.kernel.op_cute",
)


_DECORATOR_AXES = {
    "handles_buff": "buffbase_order",
    "handles_prefix": "prefix",
    "handles_base_id": "base_id",
}


def _decorator_name(dec: ast.expr) -> str | None:
    """Return the bare decorator-call name (``"handles_buff"``) or None."""
    if isinstance(dec, ast.Call):
        target = dec.func
    else:
        target = dec
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _parse_entry_list(node: ast.expr, mod_name: str, func_name: str) -> list[tuple[int, str]]:
    """Parse the single ``[(key, label), ...]`` literal argument."""
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise RuntimeError(
            f"{mod_name}.{func_name}: @handles_* argument is not a literal: {exc}"
        ) from None
    if not isinstance(value, (list, tuple)):
        raise RuntimeError(
            f"{mod_name}.{func_name}: @handles_* expects a list of (int, str) "
            f"tuples; got {type(value).__name__}"
        )
    out: list[tuple[int, str]] = []
    for i, entry in enumerate(value):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise RuntimeError(
                f"{mod_name}.{func_name}: @handles_* entry #{i} must be a "
                f"(int, str) tuple, got {entry!r}"
            )
        key, label = entry
        if not isinstance(key, int) or not isinstance(label, str):
            raise RuntimeError(
                f"{mod_name}.{func_name}: @handles_* entry #{i} keys must be "
                f"(int, str); got ({type(key).__name__}, {type(label).__name__})"
            )
        out.append((int(key), str(label)))
    return out


def _scan_module(path: Path, mod_name: str) -> dict[str, dict[int, tuple[str, str]]]:
    """Scan one op-module file via AST.  Returns the per-axis dicts."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, dict[int, tuple[str, str]]] = {
        axis: {} for axis in _DECORATOR_AXES.values()
    }
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("op_"):
            continue
        for dec in node.decorator_list:
            dec_name = _decorator_name(dec)
            if dec_name not in _DECORATOR_AXES:
                continue
            if not isinstance(dec, ast.Call) or len(dec.args) != 1:
                raise RuntimeError(
                    f"{mod_name}.{node.name}: @{dec_name} must be called with "
                    f"exactly one positional list argument"
                )
            axis = _DECORATOR_AXES[dec_name]
            entries = _parse_entry_list(dec.args[0], mod_name, node.name)
            bucket = out[axis]
            for key, label in entries:
                if key in bucket and bucket[key] != (node.name, label):
                    raise RuntimeError(
                        f"@{dec_name} key={key} declared twice with conflict: "
                        f"{bucket[key]!r} vs {(node.name, label)!r}"
                    )
                bucket[key] = (node.name, label)
    return out


def collect_handler_axes(
    op_modules: Iterable[str] = _OP_MODULES,
) -> dict[str, dict[int, tuple[str, str]]]:
    """Scan every op-module and return the merged per-axis dispatch tables.

    Conflict between modules (same key claimed by two handlers) raises
    immediately — there is no defensible last-write-wins semantics for
    a pak axis.  Returned dict has three keys: ``buffbase_order``,
    ``prefix``, ``base_id``.  Each value is ``{key: (handler_name,
    alias_or_note)}``.
    """
    merged: dict[str, dict[int, tuple[str, str]]] = {
        axis: {} for axis in _DECORATOR_AXES.values()
    }
    for mod_name in op_modules:
        path = ROOT / (mod_name.replace(".", "/") + ".py")
        per_mod = _scan_module(path, mod_name)
        for axis, bucket in per_mod.items():
            for key, value in bucket.items():
                existing = merged[axis].get(key)
                if existing is not None and existing != value:
                    raise RuntimeError(
                        f"axis={axis} key={key} declared in two modules: "
                        f"{existing!r} vs {value!r} (in {mod_name})"
                    )
                merged[axis][key] = value
    return merged


def axes_with_handler_indices(
    handler_indices: dict[str, int],
    op_modules: Iterable[str] = _OP_MODULES,
) -> dict[str, dict[int, int]]:
    """Resolve handler names to integer indices for codegen consumption.

    Helper used by :mod:`prefixes.py`: pak axis key → ``handler_idx``
    is the final shape needed by ``prefix_handler_map.json`` and the
    runtime classifier.  Aliases / notes are dropped here.
    """
    axes = collect_handler_axes(op_modules)
    out: dict[str, dict[int, int]] = {
        axis: {} for axis in _DECORATOR_AXES.values()
    }
    for axis, bucket in axes.items():
        for key, (handler_name, _label) in bucket.items():
            const = (
                "H_NOOP" if handler_name == "_noop"
                else "H_" + handler_name[3:].upper() if handler_name.startswith("op_")
                else "H_" + handler_name.upper()
            )
            if const not in handler_indices:
                raise RuntimeError(
                    f"axis={axis} key={key}: handler {handler_name!r} resolves "
                    f"to {const!r} which is not in handler_indices"
                )
            out[axis][key] = handler_indices[const]
    return out
