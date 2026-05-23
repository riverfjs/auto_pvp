"""Temporary static-data audit prototype.

This script intentionally lives under _experiments. It inventories module-level
data literals and generated imports so the compiler redesign can separate
generated facts, structural decoders, enum adapters, policy, and semantic debt.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MD = Path(__file__).with_name("current_static_data_audit.md")
DEFAULT_JSON = Path(__file__).with_name("current_static_data_audit.json")

SCAN_ROOTS = (
    "roco/engine",
    "roco/common",
    "roco/compiler_v2",
    "roco/data",
)

KNOWN_DECISIONS: dict[str, tuple[str, str]] = {}

MANUAL_SEMANTIC_BINDINGS: dict[str, str] = {
    "roco/compiler_v2/artifacts.py:<module>:MARK_NOTE_BY_IDX": (
        "Manual MarkIdx -> DESC_NOTE note adapter used to build canonical mark defs."
    ),
    "roco/compiler_v2/buff_immunity_decoders.py:<module>:IMMUNITY_SPECS": (
        "Manual immunity keyword/bit policy; pak desc is scanned but the semantic categories are hand-owned."
    ),
    "roco/compiler_v2/effect_codegen/ability_flags_from_effects.py:<module>:_EDITOR_NAME_TO_FLAG": (
        "Manual EFFECT_CONF.editor_name -> AbilityFlag semantic binding."
    ),
    "roco/compiler_v2/effect_codegen/ability_flags_from_effects.py:<module>:_BUFF_EDITOR_NAME_TO_FLAG": (
        "Manual BUFF_CONF.editor_name -> AbilityFlag semantic binding."
    ),
    "roco/compiler_v2/effect_codegen/params.py:<module>:_MARK_HANDLER_NAMES": (
        "Manual handler-name family used to identify mark handlers after append-only registry reordering."
    ),
    "roco/compiler_v2/effect_families/ignored.py:<module>:VISUAL_KEYWORDS": (
        "Manual audit heuristic for visual/no-combat candidate language."
    ),
}


@dataclass(frozen=True)
class Assignment:
    file: str
    line: int
    scope: str
    name: str
    value_kind: str
    size: int | None
    classification: str
    action: str


@dataclass(frozen=True)
class GeneratedImport:
    file: str
    line: int
    module: str
    names: tuple[str, ...]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_python_files() -> list[Path]:
    out: list[Path] = []
    for scan_root in SCAN_ROOTS:
        root = ROOT / scan_root
        if not root.exists():
            continue
        out.extend(sorted(root.rglob("*.py")))
    return out


def value_shape(value: ast.AST) -> tuple[str, int | None] | None:
    if isinstance(value, ast.Dict):
        return "dict", len(value.keys)
    if isinstance(value, ast.Tuple):
        return "tuple", len(value.elts)
    if isinstance(value, ast.List):
        return "list", len(value.elts)
    if isinstance(value, ast.Set):
        return "set", len(value.elts)
    return None


def target_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(target_names(elt))
        return tuple(names)
    return ()


class DataBindingVisitor(ast.NodeVisitor):
    def __init__(self, file_rel: str) -> None:
        self.file_rel = file_rel
        self.scope: list[str] = []
        self.found: list[Assignment] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node, ast.Assign):
            shape = value_shape(node.value)
            if shape is None:
                self.generic_visit(node)
                return
            names = tuple(name for target in node.targets for name in target_names(target))
        value_kind, size = shape
        for name in names:
            self._append(node.lineno, name, value_kind, size)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            self.generic_visit(node)
            return
        shape = value_shape(node.value)
        if shape is None:
            self.generic_visit(node)
            return
        value_kind, size = shape
        for name in target_names(node.target):
            self._append(node.lineno, name, value_kind, size)
        self.generic_visit(node)

    def _append(self, line: int, name: str, value_kind: str, size: int | None) -> None:
        scope = ".".join(self.scope) if self.scope else "<module>"
        classification, action = classify_assignment(self.file_rel, name, scope)
        self.found.append(
            Assignment(self.file_rel, line, scope, name, value_kind, size, classification, action)
        )


def data_assignments(path: Path, tree: ast.Module) -> list[Assignment]:
    visitor = DataBindingVisitor(rel(path))
    visitor.visit(tree)
    return visitor.found


def generated_imports(path: Path, tree: ast.Module) -> list[GeneratedImport]:
    found: list[GeneratedImport] = []
    file_rel = rel(path)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module != "roco.generated" and not module.startswith("roco.generated."):
            continue
        names = tuple(alias.name for alias in node.names)
        found.append(GeneratedImport(file_rel, node.lineno, module, names))
    return found


def classify_assignment(file_rel: str, name: str, scope: str) -> tuple[str, str]:
    if name == "__all__":
        return "module_export", "Allowed module export list; not static battle data."
    manual_key = f"{file_rel}:{scope}:{name}"
    if manual_key in MANUAL_SEMANTIC_BINDINGS:
        return "manual_semantic_binding", MANUAL_SEMANTIC_BINDINGS[manual_key]
    scoped_key = f"{file_rel}:{scope}:{name}"
    if scoped_key in KNOWN_DECISIONS:
        return KNOWN_DECISIONS[scoped_key]
    key = f"{file_rel}:{name}"
    if key in KNOWN_DECISIONS:
        return KNOWN_DECISIONS[key]
    if file_rel.startswith("roco/compiler_v2/semantics.py"):
        return "compiler_semantic_binding", "Review manually; move derivable facts to generated/static."
    if file_rel.startswith("roco/compiler_v2/artifacts.py"):
        return "compiler_emitter_internal", "Allowed as emitter implementation, not a data source."
    if file_rel.startswith("roco/compiler_v2/"):
        return "compiler_model_or_source_cache", "Allowed when it describes compiler internals or parsed source snapshots."
    if file_rel == "roco/common/enums.py":
        return "enum_adapter", "Allowed short-term; generated enum validation should cover drift."
    if file_rel == "roco/common/natures.py":
        return "generated_consumer", "Generated from NATURE_CONF/ATTRIBUTE_CONF via roco.generated.natures."
    if file_rel.startswith("roco/common/"):
        return "common_runtime_constant", "Allowed when it is bit layout or typed runtime policy."
    if file_rel == "roco/data/parse_pak.py":
        return "canonical_adapter_debt", "Audit source; prefer shared generated adapters."
    if file_rel.startswith("roco/data/"):
        return "data_pipeline_internal", "Allowed when it is transport/schema logic, not battle rules."
    if file_rel == "roco/engine/kernel/ctx.py" and scope == "<module>" and name == "_DEFAULTS":
        return (
            "engine_runtime_ctx_defaults",
            "Allowed runtime StageCtx default fields; not pak static data, id mapping, or order mapping.",
        )
    if file_rel.startswith("roco/engine/"):
        return "engine_local_constant", "Must not contain pak id/effect id/order data."
    return "unclassified", "Review manually."


def known_decision(item: Assignment) -> bool:
    return (
        f"{item.file}:{item.scope}:{item.name}" in KNOWN_DECISIONS
        or f"{item.file}:{item.name}" in KNOWN_DECISIONS
    )


def is_priority_debt(item: Assignment) -> bool:
    if item.name == "__all__":
        return False
    if known_decision(item):
        return True
    if item.scope != "<module>":
        return False
    return item.classification in {
        "semantic_debt",
        "duplicated_adapter",
        "generatable_adapter",
        "domain_seed_needs_source",
        "legacy_shadow",
        "jsonl_legacy_edge",
        "canonical_adapter_debt",
    }


def is_engine_static_data(item: Assignment) -> bool:
    if item.name == "__all__":
        return False
    if item.classification == "engine_runtime_ctx_defaults":
        return False
    if not item.file.startswith("roco/engine/"):
        return False
    if item.scope == "<module>":
        return True
    return item.value_kind == "dict" and bool(item.size)


def is_manual_semantic_binding(item: Assignment) -> bool:
    return item.classification == "manual_semantic_binding"


def build_report() -> dict[str, Any]:
    assignments: list[Assignment] = []
    imports: list[GeneratedImport] = []
    parse_errors: list[str] = []
    for path in iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            parse_errors.append(f"{rel(path)}:{exc.lineno}: {exc.msg}")
            continue
        assignments.extend(data_assignments(path, tree))
        imports.extend(generated_imports(path, tree))
    class_counts = Counter(item.classification for item in assignments)
    debt = [item for item in assignments if is_priority_debt(item)]
    engine_assignments = [item for item in assignments if is_engine_static_data(item)]
    manual_semantic_bindings = [
        item for item in assignments if is_manual_semantic_binding(item)
    ]
    return {
        "scan_roots": list(SCAN_ROOTS),
        "summary": dict(sorted(class_counts.items())),
        "generated_imports": [asdict(item) for item in imports],
        "assignments": [asdict(item) for item in assignments],
        "priority_debt": [asdict(item) for item in debt],
        "engine_assignments": [asdict(item) for item in engine_assignments],
        "manual_semantic_bindings": [asdict(item) for item in manual_semantic_bindings],
        "parse_errors": parse_errors,
    }


def md_table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    summary_rows = [(k, v) for k, v in report["summary"].items()]
    debt_rows = [
        (
            item["classification"],
            item["file"],
            item["line"],
            item["scope"],
            item["name"],
            item["value_kind"],
            item["size"],
            item["action"],
        )
        for item in report["priority_debt"]
    ]
    engine_rows = [
        (
            item["file"],
            item["line"],
            item["scope"],
            item["name"],
            item["value_kind"],
            item["size"],
            item["classification"],
        )
        for item in report["engine_assignments"]
    ]
    manual_rows = [
        (
            item["file"],
            item["line"],
            item["scope"],
            item["name"],
            item["value_kind"],
            item["size"],
            item["action"],
        )
        for item in report["manual_semantic_bindings"]
    ]
    import_rows = [
        (item["file"], item["line"], item["module"], ", ".join(item["names"]))
        for item in report["generated_imports"]
    ]

    parts = [
        "# Current static data audit",
        "",
        "Generated by `_experiments/data_audit/audit_static_data.py`.",
        "",
        "## Summary",
        "",
        md_table(("classification", "count"), summary_rows),
        "",
        "## Priority debt",
        "",
        md_table(("class", "file", "line", "scope", "name", "kind", "size", "action"), debt_rows),
        "",
        "## Engine data literals",
        "",
        "These are not automatically bugs, but they are the first gate for handwritten battle data in engine.",
        "",
        md_table(("file", "line", "scope", "name", "kind", "size", "class"), engine_rows),
        "",
        "## Manual semantic bindings",
        "",
        "These are not generated data and should stay small, tested, and explicit.",
        "",
        md_table(("file", "line", "scope", "name", "kind", "size", "action"), manual_rows),
        "",
        "## Generated imports",
        "",
        md_table(("file", "line", "module", "names"), import_rows),
        "",
    ]
    if report["parse_errors"]:
        parts.extend([
            "## Parse errors",
            "",
            "\n".join(f"- {err}" for err in report["parse_errors"]),
            "",
        ])
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()

    report = build_report()
    args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_json}")
    print(f"priority_debt={len(report['priority_debt'])}")
    print(f"engine_assignments={len(report['engine_assignments'])}")
    print(f"manual_semantic_bindings={len(report['manual_semantic_bindings'])}")


if __name__ == "__main__":
    main()
