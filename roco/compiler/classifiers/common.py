"""Shared classifier primitives for canonical JSONL records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from roco.compiler.effect_model import EffectTag, Timing
from roco.data.utils import RULES_DIR, iter_jsonl
from roco.common.enums import SkillCategory

EffectRecord = dict[str, Any]
ManualRules = dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    flags: int
    effects: tuple[EffectRecord, ...]
    gaps: tuple[EffectRecord, ...]
    source: str

    @property
    def status(self) -> str:
        return "ok" if not self.gaps else "needs_manual"

    def meta(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "gaps": list(self.gaps),
        }


def load_manual_rules(kind: str) -> ManualRules:
    """Load exact-name manual classification rules for a canonical owner kind."""
    path = RULES_DIR / f"{kind}_effects_manual.jsonl"
    if not path.exists():
        return {}
    rules: ManualRules = {}
    for record in iter_jsonl(path):
        name = str(record.get("name", "")).strip()
        if name:
            rules[name] = record
    return rules


def apply_manual(kind: str, name: str, generated: Iterable[EffectRecord], manual_rules: ManualRules) -> tuple[tuple[EffectRecord, ...], str]:
    rule = manual_rules.get(name)
    if not rule:
        return tuple(dedupe(generated)), "generated"
    manual = tuple(dict(row) for row in rule.get("effects", ()))
    mode = str(rule.get("mode", "extend"))
    if mode == "replace":
        return tuple(dedupe(manual)), f"manual:{kind}:replace"
    return tuple(dedupe(tuple(generated) + manual)), f"manual:{kind}:extend"


def missing_gaps(source_type: str, name: str, text: str, effects: Iterable[EffectRecord]) -> tuple[EffectRecord, ...]:
    if tuple(effects) or not text.strip():
        return ()
    return ({
        "primitive": name,
        "timing": None,
        "params": {},
        "reason": "structured_effect_missing",
    },)


def dedupe(rows: Iterable[EffectRecord]) -> list[EffectRecord]:
    seen: set[tuple[Any, ...]] = set()
    result: list[EffectRecord] = []
    for index, row in enumerate(rows):
        clean = {
            "timing": timing_name(row.get("timing")),
            "tag": tag_name(row.get("tag")),
            "params": dict(row.get("params", {}) or {}),
            "condition": str(row.get("condition", "") or ""),
            "sort_order": int(row.get("sort_order", index)),
        }
        key = (
            clean["timing"],
            clean["tag"],
            freeze(clean["params"]),
            clean["condition"],
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((key, freeze(val)) for key, val in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def timing_name(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, Timing):
        return raw.name
    if isinstance(raw, int):
        return Timing(raw).name
    return str(raw)


def tag_name(raw: object) -> str:
    if isinstance(raw, EffectTag):
        return raw.name
    if isinstance(raw, int):
        return EffectTag(raw).name
    return str(raw)


def category(raw: object) -> SkillCategory:
    if isinstance(raw, SkillCategory):
        return raw
    mapping = {
        "物攻": SkillCategory.PHYSICAL,
        "魔攻": SkillCategory.MAGICAL,
        "防御": SkillCategory.DEFENSE,
        "状态": SkillCategory.STATUS,
    }
    text = str(raw or "").strip()
    if text not in mapping:
        raise ValueError(f"unknown skill category: {raw!r}")
    return mapping[text]


def int_value(raw: object, default: int) -> int:
    try:
        if raw is None or raw == "":
            return default
        return int(raw)
    except (TypeError, ValueError):
        return default
