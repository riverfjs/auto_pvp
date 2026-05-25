"""Engine-owned kernel handler manifest.

The compiler does not know about ``op_*`` functions or handler indices.  This
module scans engine op modules and derives the runtime handler order used by
the generated dispatch table.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]

OP_MODULES: tuple[str, ...] = (
    "roco.engine.kernel.ops.damage",
    "roco.engine.kernel.ops.buffs",
    "roco.engine.kernel.ops.skill",
    "roco.engine.kernel.ops.combat",
    "roco.engine.kernel.ops.resources",
    "roco.engine.kernel.ops.marks",
    "roco.engine.kernel.ops.status",
    "roco.engine.kernel.ops.cute",
)


@lru_cache(maxsize=1)
def module_functions() -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for mod_name in OP_MODULES:
        path = ROOT / (mod_name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = tuple(
            node.name for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("op_")
        )
        result[mod_name] = names
    return result


@lru_cache(maxsize=1)
def load_handler_order() -> tuple[str, ...]:
    discovered = {
        name for names in module_functions().values()
        for name in names
    }
    return ("_noop", *tuple(sorted(discovered)))
