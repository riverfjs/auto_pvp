"""Compile canonical skill/ability records into data-owned effect rows.

The importer is intentionally dumb: it validates and stores canonical rows.
This module is the data-build classification layer, mirroring NRC_AI's
manual-overrides-plus-generated-audit shape without becoming a runtime API.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from roco.data.utils import RULES_DIR, iter_jsonl
from roco.engine.effect_compile import compile_skill_effects
from roco.engine.effect_model import EffectTag, Timing
from roco.engine.skill_tags import classify
from roco.engine.state import SkillCategory, SkillData, normalize_element_name


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


_ABILITY_PATTERNS: tuple[tuple[re.Pattern[str], EffectRecord], ...] = (
    (re.compile(r"力竭.*不扣MP|不扣MP"), {"timing": "PASSIVE", "tag": "FAINT_NO_MP_LOSS", "params": {}}),
    (re.compile(r"先于敌方.*威力\+?(\d+)%"), {"timing": "CALC_DAMAGE", "tag": "FIRST_STRIKE_POWER_BONUS", "params": {"bonus_pct": 0.5}}),
    (re.compile(r"每回合.*(?:回复|获得|增加)(\d+)能量|每回合能量\+(\d+)"), {"timing": "TURN_END", "tag": "ENERGY_REGEN_PER_TURN", "params": {"amount": 1}}),
    (re.compile(r"灼烧.*不(?:会)?衰减|灼烧不衰减"), {"timing": "PASSIVE", "tag": "BURN_NO_DECAY", "params": {}}),
    (re.compile(r"中毒.*额外(?:结算|伤害)|额外.*中毒"), {"timing": "PASSIVE", "tag": "EXTRA_POISON_TICK", "params": {}}),
    (re.compile(r"额外.*冻结|冻结.*额外"), {"timing": "PASSIVE", "tag": "EXTRA_FREEZE_ON_FREEZE", "params": {"extra": 2}}),
)

_CN_NUM = {
    "": 1,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_MARK_TAGS = {
    "中毒": ("POISON_MARK", "enemy"),
    "湿润": ("MOISTURE_MARK", "self"),
    "龙噬": ("DRAGON_MARK", "self"),
    "风起": ("WIND_MARK", "self"),
    "蓄电": ("CHARGE_MARK", "self"),
    "光合": ("SOLAR_MARK", "self"),
    "攻击": ("ATTACK_MARK", "self"),
    "减速": ("SLOW_MARK", "enemy"),
    "迟缓": ("SLUGGISH_MARK", "self"),
    "降灵": ("SPIRIT_MARK", "enemy"),
    "星陨": ("METEOR_MARK", "enemy"),
    "荆刺": ("THORN_MARK", "enemy"),
    "棘刺": ("THORN_MARK", "enemy"),
    "蓄势": ("MOMENTUM_MARK", "self"),
}

_RE_MARK_GAIN = re.compile(
    r"(?P<target>自己|敌方|目标)?\s*获得\s*(?P<stacks>\d+|一|二|两|三|四|五|六|七|八|九|十)?\s*层?\s*"
    r"(?P<mark>中毒|湿润|龙噬|风起|蓄电|光合|攻击|减速|迟缓|降灵|星陨|荆刺|棘刺|蓄势)印记"
)


def load_manual_rules(kind: str) -> ManualRules:
    """Load exact-name manual classification rules for `skill` or `ability`."""
    path = RULES_DIR / f"{kind}_effects_manual.jsonl"
    if not path.exists():
        return {}
    rules: ManualRules = {}
    for record in iter_jsonl(path):
        name = str(record.get("name", "")).strip()
        if name:
            rules[name] = record
    return rules


def classify_skill_record(record: Mapping[str, Any], manual_rules: ManualRules | None = None) -> ClassificationResult:
    """Classify one canonical skill record into canonical effect records."""
    manual_rules = manual_rules if manual_rules is not None else load_manual_rules("skill")
    category = _category(record.get("category", "物攻"))
    skill = SkillData(
        name=str(record.get("name", "")),
        element=normalize_element_name(str(record.get("element", "普通"))),
        category=category,
        energy=_int(record.get("energy"), 0),
        power=_int(record.get("power"), 0),
        effect=str(record.get("effect_text", "")),
    )
    classify(skill)
    generated = tuple(_skill_effect_to_record(row) for row in compile_skill_effects(0, skill))
    generated = generated + _generated_mark_effects(skill.effect)
    effects, source = _apply_manual("skill", skill.name, generated, manual_rules)
    gaps = _missing_gaps("skill", skill.name, skill.effect, effects)
    return ClassificationResult(int(skill.effect_flags), tuple(effects), gaps, source)


def classify_ability_record(record: Mapping[str, Any], manual_rules: ManualRules | None = None) -> ClassificationResult:
    """Classify one canonical ability record into canonical effect records."""
    manual_rules = manual_rules if manual_rules is not None else load_manual_rules("ability")
    name = str(record.get("name", "")).strip()
    desc = str(record.get("description", "")).strip()
    generated = _generated_ability_effects(desc)
    effects, source = _apply_manual("ability", name, generated, manual_rules)
    gaps = _missing_gaps("ability", name, desc, effects)
    return ClassificationResult(0, tuple(effects), gaps, source)


def refresh_skill_classification(record: Mapping[str, Any], manual_rules: ManualRules | None = None) -> dict[str, Any]:
    result = classify_skill_record(record, manual_rules)
    updated = dict(record)
    updated["flags"] = result.flags
    updated["effects"] = list(result.effects)
    updated["classification"] = result.meta()
    return updated


def refresh_ability_classification(record: Mapping[str, Any], manual_rules: ManualRules | None = None) -> dict[str, Any]:
    result = classify_ability_record(record, manual_rules)
    updated = dict(record)
    updated["flags"] = result.flags
    updated["effects"] = list(result.effects)
    updated["classification"] = result.meta()
    return updated


def _generated_ability_effects(description: str) -> tuple[EffectRecord, ...]:
    rows: list[EffectRecord] = []
    for pattern, effect in _ABILITY_PATTERNS:
        match = pattern.search(description)
        if not match:
            continue
        row = {"timing": effect["timing"], "tag": effect["tag"], "params": dict(effect.get("params", {}))}
        if row["tag"] in {"FIRST_STRIKE_POWER_BONUS", "ENERGY_REGEN_PER_TURN"}:
            numbers = [int(g) for g in match.groups() if g]
            if numbers and row["tag"] == "FIRST_STRIKE_POWER_BONUS":
                row["params"]["bonus_pct"] = numbers[0] / 100.0
            elif numbers and row["tag"] == "ENERGY_REGEN_PER_TURN":
                row["params"]["amount"] = numbers[0]
        rows.append(row)
    return tuple(_dedupe(rows))


def _generated_mark_effects(effect_text: str) -> tuple[EffectRecord, ...]:
    rows: list[EffectRecord] = []
    for match in _RE_MARK_GAIN.finditer(effect_text):
        mark = match.group("mark")
        tag, default_target = _MARK_TAGS[mark]
        target_word = match.group("target") or ""
        target = "self" if target_word == "自己" else "enemy" if target_word in {"敌方", "目标"} else default_target
        rows.append({
            "timing": "AFTER_MOVE",
            "tag": tag,
            "params": {"target": target, "stacks": _cn_int(match.group("stacks"))},
        })
    if "驱散双方所有印记" in effect_text or "驱散所有印记" in effect_text:
        rows.append({"timing": "AFTER_MOVE", "tag": "DISPEL_MARKS", "params": {"condition": "not_blocked"}})
    elif "驱散敌方所有印记" in effect_text or "驱散目标所有印记" in effect_text:
        rows.append({"timing": "AFTER_MOVE", "tag": "DISPEL_ENEMY_MARKS", "params": {}})
    if "偷取印记" in effect_text:
        rows.append({"timing": "AFTER_MOVE", "tag": "STEAL_MARKS", "params": {}})
    return tuple(_dedupe(rows))


def _apply_manual(kind: str, name: str, generated: Iterable[EffectRecord], manual_rules: ManualRules) -> tuple[tuple[EffectRecord, ...], str]:
    rule = manual_rules.get(name)
    if not rule:
        return tuple(_dedupe(generated)), "generated"
    manual = tuple(dict(row) for row in rule.get("effects", ()))
    mode = str(rule.get("mode", "extend"))
    if mode == "replace":
        return tuple(_dedupe(manual)), f"manual:{kind}:replace"
    return tuple(_dedupe(tuple(generated) + manual)), f"manual:{kind}:extend"


def _missing_gaps(source_type: str, name: str, text: str, effects: Iterable[EffectRecord]) -> tuple[EffectRecord, ...]:
    if tuple(effects) or not text.strip():
        return ()
    return ({
        "primitive": name,
        "timing": None,
        "params": {},
        "reason": "structured_effect_missing",
    },)


def _skill_effect_to_record(row) -> EffectRecord:
    return {
        "timing": row.effect.timing.name,
        "tag": row.effect.tag.name,
        "params": dict(row.effect.params),
        "condition": row.effect.condition,
        "sort_order": row.sort_order,
    }


def _dedupe(rows: Iterable[EffectRecord]) -> list[EffectRecord]:
    seen: set[tuple[Any, ...]] = set()
    result: list[EffectRecord] = []
    for index, row in enumerate(rows):
        clean = {
            "timing": _timing_name(row.get("timing")),
            "tag": _tag_name(row.get("tag")),
            "params": dict(row.get("params", {}) or {}),
            "condition": str(row.get("condition", "") or ""),
            "sort_order": int(row.get("sort_order", index)),
        }
        key = (
            clean["timing"],
            clean["tag"],
            tuple(sorted(clean["params"].items())),
            clean["condition"],
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _timing_name(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, Timing):
        return raw.name
    if isinstance(raw, int):
        return Timing(raw).name
    return str(raw)


def _tag_name(raw: object) -> str:
    if isinstance(raw, EffectTag):
        return raw.name
    if isinstance(raw, int):
        return EffectTag(raw).name
    return str(raw)


def _category(raw: object) -> SkillCategory:
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


def _int(raw: object, default: int) -> int:
    try:
        if raw is None or raw == "":
            return default
        return int(raw)
    except (TypeError, ValueError):
        return default


def _cn_int(raw: object) -> int:
    text = str(raw or "")
    if text.isdigit():
        return int(text)
    return _CN_NUM.get(text, 1)
