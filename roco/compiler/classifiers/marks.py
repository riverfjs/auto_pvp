"""Mark primitive extraction from canonical skill text."""

from __future__ import annotations

import re

from roco.compiler.classifiers.common import EffectRecord, dedupe

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


def generated_mark_effects(effect_text: str) -> tuple[EffectRecord, ...]:
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
    return tuple(dedupe(rows))


def _cn_int(raw: object) -> int:
    text = str(raw or "")
    if text.isdigit():
        return int(text)
    return _CN_NUM.get(text, 1)
