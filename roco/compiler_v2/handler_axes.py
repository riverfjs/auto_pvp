"""Collect handler-owned pak-axis declarations from engine op modules.

The compiler owns the join from pak/Lua static data to generated lookup
tables, but the engine owns the statement "this op implements that
feature".  Engine modules express that with identity decorators from
``roco.engine.kernel.op_meta``.  This collector reads those decorators via
AST so generation has no import side effects.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]

OP_MODULES: tuple[str, ...] = (
    "roco.engine.kernel.op_mods.damage",
    "roco.engine.kernel.op_mods.buffs",
    "roco.engine.kernel.op_mods.skill",
    "roco.engine.kernel.op_mods.combat",
    "roco.engine.kernel.op_resources",
    "roco.engine.kernel.op_marks",
    "roco.engine.kernel.op_status",
    "roco.engine.kernel.op_cute",
)

_DECORATOR_AXES: dict[str, tuple[str, type]] = {
    "handles_buff": ("buff_type", str),
    "handles_prefix": ("prefix_type", str),
}


@dataclass(frozen=True)
class ResolvedHandlerAxes:
    """Handler axes resolved to generated integer ids."""

    buffbase_order: dict[int, int]
    prefix: dict[int, int]
    base_id: dict[int, int]
    prefix_aliases: dict[int, str]
    raw: dict[str, dict[int | str, tuple[str, str]]]


def _decorator_name(dec: ast.expr) -> str | None:
    if isinstance(dec, ast.Call):
        target = dec.func
    else:
        target = dec
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _parse_entry_list(
    node: ast.expr,
    mod_name: str,
    func_name: str,
    key_type: type,
    require_buff_symbol: bool,
) -> list[tuple[int | str, str]]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise RuntimeError(
            f"{mod_name}.{func_name}: @handles_* argument is not a literal: {exc}"
        ) from None
    if not isinstance(value, (list, tuple)):
        raise RuntimeError(
            f"{mod_name}.{func_name}: @handles_* expects a list of (key, str) "
            f"tuples; got {type(value).__name__}"
        )

    out: list[tuple[int | str, str]] = []
    for i, entry in enumerate(value):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise RuntimeError(
                f"{mod_name}.{func_name}: @handles_* entry #{i} must be a "
                f"(key, str) tuple, got {entry!r}"
            )
        key, label = entry
        if not isinstance(key, key_type) or not isinstance(label, str):
            raise RuntimeError(
                f"{mod_name}.{func_name}: @handles_* entry #{i} keys must be "
                f"({key_type.__name__}, str); got "
                f"({type(key).__name__}, {type(label).__name__})"
            )
        if require_buff_symbol and not str(key).startswith("BFT_"):
            raise RuntimeError(
                f"{mod_name}.{func_name}: @handles_* entry #{i} must use an "
                f"Enum.BuffType symbol, got {key!r}"
            )
        out.append((key, label))
    return out


def _scan_module(path: Path, mod_name: str) -> dict[str, dict[int | str, tuple[str, str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, dict[int | str, tuple[str, str]]] = {
        axis: {} for axis, _ in _DECORATOR_AXES.values()
    }
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("op_"):
            continue
        for dec in node.decorator_list:
            dec_name = _decorator_name(dec)
            spec = _DECORATOR_AXES.get(dec_name or "")
            if spec is None:
                continue
            if not isinstance(dec, ast.Call) or len(dec.args) != 1:
                raise RuntimeError(
                    f"{mod_name}.{node.name}: @{dec_name} must be called with "
                    f"exactly one positional list argument"
                )
            axis, key_type = spec
            entries = _parse_entry_list(
                dec.args[0],
                mod_name,
                node.name,
                key_type,
                require_buff_symbol=axis in {"buff_type", "prefix_type"},
            )
            bucket = out[axis]
            for key, label in entries:
                existing = bucket.get(key)
                if existing is not None and existing != (node.name, label):
                    raise RuntimeError(
                        f"@{dec_name} key={key!r} declared twice with conflict: "
                        f"{existing!r} vs {(node.name, label)!r}"
                    )
                bucket[key] = (node.name, label)
    return out


def collect_handler_axes(
    op_modules: Iterable[str] = OP_MODULES,
) -> dict[str, dict[int | str, tuple[str, str]]]:
    """Return raw handler-owned axes from engine decorators."""

    merged: dict[str, dict[int | str, tuple[str, str]]] = {
        axis: {} for axis, _ in _DECORATOR_AXES.values()
    }
    for mod_name in op_modules:
        path = ROOT / (mod_name.replace(".", "/") + ".py")
        per_mod = _scan_module(path, mod_name)
        for axis, bucket in per_mod.items():
            for key, value in bucket.items():
                existing = merged[axis].get(key)
                if existing is not None and existing != value:
                    raise RuntimeError(
                        f"axis={axis} key={key!r} declared in two modules: "
                        f"{existing!r} vs {value!r} (in {mod_name})"
                    )
                merged[axis][key] = value
    return merged


def _func_to_const(name: str) -> str:
    if name == "_noop":
        return "H_NOOP"
    if name.startswith("op_"):
        return "H_" + name[3:].upper()
    return "H_" + name.upper()


def _resolve_handler(handler_indices: dict[str, int], axis: str, key: int | str, name: str) -> int:
    const = _func_to_const(name)
    if const not in handler_indices:
        raise RuntimeError(
            f"axis={axis} key={key!r}: handler {name!r} resolves to {const!r} "
            f"which is not in handler_indices"
        )
    return handler_indices[const]


def _buff_type_value(buff_type_enum: dict[str, int], symbol: int | str) -> int:
    if not isinstance(symbol, str):
        raise RuntimeError(f"Enum.BuffType symbol must be a string, got {symbol!r}")
    value = buff_type_enum.get(symbol)
    if value is None:
        raise RuntimeError(f"Enum.BuffType has no member {symbol!r}")
    return int(value)


def _put_unique(mapping: dict[int, int], key: int, value: int, context: str) -> None:
    existing = mapping.get(key)
    if existing is not None and existing != value:
        raise RuntimeError(f"{context}: resolved key {key} conflicts: {existing} vs {value}")
    mapping[key] = value


def resolve_handler_axes(
    handler_indices: dict[str, int],
    lua_enums: dict[str, dict[str, int]],
    op_modules: Iterable[str] = OP_MODULES,
    buffbase_rows: dict[int, dict] | None = None,
) -> ResolvedHandlerAxes:
    """Resolve engine declarations through generated Lua enum data.

    ``handles_buff`` and ``handles_prefix`` use ``Enum.BuffType`` symbols
    rather than numeric ids.  Exact outliers are generated from pak
    structures in :mod:`roco.compiler_v2.artifacts`, not from engine-owned
    pak names.
    """

    buff_type_enum = lua_enums.get("BuffType")
    if buff_type_enum is None:
        raise RuntimeError("Lua static bundle is missing Enum.BuffType")

    raw = collect_handler_axes(op_modules)
    order_seed: dict[int, int] = {}
    prefix_seed: dict[int, int] = {}
    base_id_seed: dict[int, int] = {}
    prefix_aliases: dict[int, str] = {}
    _ = buffbase_rows

    for symbol, (handler_name, alias) in raw["buff_type"].items():
        order = _buff_type_value(buff_type_enum, symbol)
        handler_idx = _resolve_handler(handler_indices, "buff_type", symbol, handler_name)
        _put_unique(order_seed, order, handler_idx, f"buff_type={symbol!r}")
        prefix_aliases[2000 + order] = alias

    for symbol, (handler_name, alias) in raw["prefix_type"].items():
        prefix = 2000 + _buff_type_value(buff_type_enum, symbol)
        handler_idx = _resolve_handler(handler_indices, "prefix_type", symbol, handler_name)
        _put_unique(prefix_seed, prefix, handler_idx, f"prefix_type={symbol!r}")
        prefix_aliases[prefix] = alias

    return ResolvedHandlerAxes(
        buffbase_order=dict(sorted(order_seed.items())),
        prefix=dict(sorted(prefix_seed.items())),
        base_id=dict(sorted(base_id_seed.items())),
        prefix_aliases=dict(sorted(prefix_aliases.items())),
        raw=raw,
    )
