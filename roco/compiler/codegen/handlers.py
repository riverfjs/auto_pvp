"""Codegen for handler indices / order / table / registry.

Discovers ``op_*`` functions in ``roco.engine.kernel`` via AST parse and
emits four artifacts under ``roco/generated/``:

* ``handler_indices.py`` — ``H_*`` constants, one per registered handler.
* ``handler_order.py``   — ``HANDLER_ORDER`` tuple of canonical names.
* ``handler_table.py``   — static ``HANDLERS`` tuple with explicit
  per-module imports (replaces ``ops.py`` runtime ``dir()`` assembly).
* ``handler_registry.json`` — append-only registry of op names.

The registry is the single source of truth for *handler ordering*; new
``op_*`` functions append at the end so existing H_* indices never shift
under us.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GEN_DIR = ROOT / "roco" / "generated"
REGISTRY_PATH = GEN_DIR / "handler_registry.json"
INDICES_PATH = GEN_DIR / "handler_indices.py"
ORDER_PATH = GEN_DIR / "handler_order.py"
TABLE_PATH = GEN_DIR / "handler_table.py"


_OP_MODULES = (
    # op_mods is a package split by topic; gen scans each submodule
    # directly so each op_* function ends up imported by its real source
    # path in the generated handler_table.
    "roco.engine.kernel.op_mods.damage",
    "roco.engine.kernel.op_mods.buffs",
    "roco.engine.kernel.op_mods.skill",
    "roco.engine.kernel.op_mods.combat",
    "roco.engine.kernel.op_resources",
    "roco.engine.kernel.op_marks",
    "roco.engine.kernel.op_status",
    "roco.engine.kernel.op_cute",
)


def _module_funcs() -> dict[str, list[str]]:
    """Return {mod_name: [op_func_names]} via AST parse — no imports."""
    result: dict[str, list[str]] = {}
    for mod_name in _OP_MODULES:
        path = ROOT / (mod_name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        result[mod_name] = [
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("op_")
        ]
    return result


def _discover_handlers() -> set[str]:
    return {name for names in _module_funcs().values() for name in names}


def _load_registry() -> list[str]:
    if REGISTRY_PATH.exists():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data["handlers"]
    return ["_noop"]


def _update_registry(existing: list[str], discovered: set[str]) -> list[str]:
    known = set(existing)
    new_handlers = sorted(discovered - known)
    return existing + new_handlers


def _save_registry(handlers: list[str]) -> None:
    data = {
        "_meta": {"version": 1, "description": "Append-only handler registry."},
        "handlers": handlers,
    }
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _func_to_const(name: str) -> str:
    if name == "_noop":
        return "H_NOOP"
    if name.startswith("op_"):
        return "H_" + name[3:].upper()
    return "H_" + name.upper()


def _write_handler_table(handlers: list[str]) -> None:
    """Emit a static HANDLERS tuple with explicit per-module imports.

    Replaces runtime dir()-based assembly in ops.py with a generated table
    every op_* function is imported by name.
    """
    func_to_module: dict[str, str] = {}
    for mod_name, names in _module_funcs().items():
        for name in names:
            func_to_module[name] = mod_name

    by_module: dict[str, list[str]] = {m: [] for m in _OP_MODULES}
    for func_name in handlers:
        if func_name == "_noop":
            continue
        mod_name = func_to_module.get(func_name)
        if mod_name is None:
            raise RuntimeError(f"handler '{func_name}' not found in any op_* module")
        by_module[mod_name].append(func_name)

    lines = [
        "# Auto-generated from handler_registry.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "from roco.engine.kernel.ctx import StageCtx",
        "",
    ]
    for mod_name in _OP_MODULES:
        names = by_module[mod_name]
        if not names:
            continue
        lines.append(f"from {mod_name} import (")
        for n in names:
            lines.append(f"    {n},")
        lines.append(")")
    lines.extend([
        "",
        "",
        "def _noop(_ctx: StageCtx, _row: tuple[int, ...]) -> None:",
        "    pass",
        "",
        "",
        "HANDLERS: tuple = (",
    ])
    for idx, name in enumerate(handlers):
        lines.append(f"    {name},  # {idx}")
    lines.extend([
        ")",
        "",
        "HANDLER_COUNT = len(HANDLERS)",
        "",
    ])
    TABLE_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_handler_artifacts() -> dict[str, int]:
    """Write all four handler artifacts, return ``{H_*: index}``."""
    discovered = _discover_handlers()
    existing = _load_registry()
    handlers = _update_registry(existing, discovered)
    _save_registry(handlers)

    missing = set(handlers[1:]) - discovered
    if missing:
        print(f"WARNING: registry has handlers not in code: {missing}", file=sys.stderr)

    index_map: dict[str, int] = {}
    lines = ["# Auto-generated from handler_registry.json — do not edit.", ""]
    for idx, func_name in enumerate(handlers):
        const = _func_to_const(func_name)
        index_map[const] = idx
        lines.append(f"{const} = {idx}")
    lines.append("")
    INDICES_PATH.write_text("\n".join(lines), encoding="utf-8")

    order_lines = [
        "# Auto-generated from handler_registry.json — do not edit.",
        "",
        "HANDLER_ORDER: tuple[str, ...] = (",
    ]
    for name in handlers:
        order_lines.append(f"    {name!r},")
    order_lines.append(")")
    order_lines.append("")
    ORDER_PATH.write_text("\n".join(order_lines), encoding="utf-8")

    _write_handler_table(handlers)
    return index_map
