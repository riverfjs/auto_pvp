"""Compile canonical skill text into immutable runtime effect rows."""

from __future__ import annotations

import re
from types import MappingProxyType

from roco.compiler.effect_model import EffectFlag, EffectSpec, EffectTag, SkillEffect, Timing
from roco.compiler.records import SkillData


_RE_HEAL_HP = re.compile(r"回复\s*(\d+)%\s*(?:HP|生命)")
_RE_HEAL_NRG = re.compile(r"回复\s*(\d+)\s*能量")
_RE_STEAL_NRG = re.compile(r"偷取\s*(\d+)\s*能量")
_RE_ENEMY_LOSE_NRG = re.compile(r"敌方失去\s*(\d+)\s*能量")
_RE_DRAIN_PCT = re.compile(r"吸血\s*(\d+)%")
_RE_DEF_PCT = re.compile(r"减伤\s*(\d+)%")
_RE_HIT_COUNT = re.compile(r"(?:连击\s*(\d+)\s*次|(\d+)\s*连击)")
_RE_BURN_N = re.compile(r"(\d+)?\s*层?\s*灼烧")
_RE_POISON_N = re.compile(r"(\d+)?\s*层?\s*中毒(?!印记)")
_RE_FREEZE_N = re.compile(r"(\d+)?\s*层?\s*冻结")
_RE_LEECH_N = re.compile(r"(\d+)?\s*层?\s*寄生")
_RE_COST_UP = re.compile(r"全技能能耗\s*\+\s*(\d+)")
_RE_HP_COST = re.compile(r"失去\s*(\d+)%\s*生命")
_RE_HIT_GROWTH = re.compile(r"连击数永久\s*\+\s*(\d+)")
_RE_POWER_GROWTH = re.compile(r"威力永久\s*\+\s*(\d+)")
_RE_STAT_UP = re.compile(r"(物攻|魔攻|物防|魔防|速度)\s*\+(\d+)%")
_RE_STAT_DOWN = re.compile(r"(物攻|魔攻|物防|魔防|速度)\s*\-(\d+)%")
_RE_ENEMY_DOWN = re.compile(r"敌方(物攻|魔攻|物防|魔防|速度)\s*\-(\d+)%")
_WEATHER_MAP = {
    "沙涌": "sandstorm",
    "沙暴": "sandstorm",
    "祈雨": "rain",
    "求雨": "rain",
    "冰雹": "snow",
    "雪天": "snow",
    "暴风雪": "snow",
}


def compile_skill_effects(skill_id: int, skill: SkillData) -> tuple[SkillEffect, ...]:
    rows: list[SkillEffect] = []
    text = skill.effect
    hit_count = _hit_count(text, skill.hit_count)

    def add(timing: Timing, tag: EffectTag, params: dict, sort_order: int) -> None:
        spec = EffectSpec(tag, timing, MappingProxyType(dict(params)))
        rows.append(SkillEffect(skill_id, spec, sort_order))

    order = 0
    if skill.power > 0 or skill.effect_flags & EffectFlag.PURE_DAMAGE:
        add(Timing.CALC_DAMAGE, EffectTag.DAMAGE, {"power": skill.power, "hit_count": hit_count}, order); order += 1
    if match := _RE_DRAIN_PCT.search(text):
        add(Timing.AFTER_MOVE, EffectTag.LIFE_DRAIN, {"pct": int(match.group(1)) / 100.0}, order); order += 1
    if match := _RE_HEAL_HP.search(text):
        add(Timing.AFTER_MOVE, EffectTag.HEAL_HP, {"pct": int(match.group(1)) / 100.0}, order); order += 1
    if match := _RE_HEAL_NRG.search(text):
        add(Timing.AFTER_MOVE, EffectTag.HEAL_ENERGY, {"amount": int(match.group(1))}, order); order += 1
    if match := _RE_STEAL_NRG.search(text):
        add(Timing.AFTER_MOVE, EffectTag.STEAL_ENERGY, {"amount": int(match.group(1))}, order); order += 1
    if match := _RE_ENEMY_LOSE_NRG.search(text):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_LOSE_ENERGY, {"amount": int(match.group(1))}, order); order += 1
    if match := _RE_DEF_PCT.search(text):
        add(Timing.BEFORE_MOVE, EffectTag.DAMAGE_REDUCTION, {"pct": int(match.group(1)) / 100.0}, order); order += 1

    for tag, stacks in (
        (EffectTag.BURN, _status_stacks(_RE_BURN_N, text)),
        (EffectTag.POISON, _status_stacks(_RE_POISON_N, text)),
        (EffectTag.FREEZE, _status_stacks(_RE_FREEZE_N, text)),
        (EffectTag.LEECH, _status_stacks(_RE_LEECH_N, text)),
    ):
        if stacks > 0:
            add(Timing.AFTER_MOVE, tag, {"stacks": stacks}, order); order += 1

    if "折返" in text or "强制换人" in text:
        add(Timing.AFTER_MOVE, EffectTag.FORCE_SWITCH, {}, order); order += 1
    if "耗尽" in text or "全额" in text:
        add(Timing.BEFORE_MOVE, EffectTag.ENERGY_ALL_IN, {}, order); order += 1
    if weather := _weather(text):
        add(Timing.AFTER_MOVE, EffectTag.WEATHER, {"type": weather, "turns": 5}, order); order += 1

    self_buff = _buff_params(text, enemy=False)
    if any(self_buff.values()):
        add(Timing.AFTER_MOVE, EffectTag.SELF_BUFF, self_buff, order); order += 1
    enemy_debuff = _buff_params(text, enemy=True)
    if any(enemy_debuff.values()):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_DEBUFF, enemy_debuff, order); order += 1

    if match := _RE_COST_UP.search(text):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_ENERGY_COST_UP, {"amount": int(match.group(1)), "turns": 3}, order); order += 1
    if match := _RE_HP_COST.search(text):
        add(Timing.BEFORE_MOVE, EffectTag.HP_FOR_ENERGY, {"pct": int(match.group(1)) / 100.0}, order); order += 1
    if match := _RE_HIT_GROWTH.search(text):
        add(Timing.AFTER_MOVE, EffectTag.PERMANENT_MOD, {"target": "hit_count", "delta": int(match.group(1))}, order); order += 1
    if match := _RE_POWER_GROWTH.search(text):
        add(Timing.AFTER_MOVE, EffectTag.PERMANENT_MOD, {"target": "power", "delta": int(match.group(1))}, order); order += 1
    if "迅捷" in text:
        add(Timing.AFTER_MOVE, EffectTag.AGILITY, {}, order); order += 1
    return tuple(rows)


def _hit_count(text: str, fallback: int) -> int:
    if match := _RE_HIT_COUNT.search(text):
        return max(1, int(match.group(1) or match.group(2)))
    return max(1, fallback)


def _status_stacks(pattern: re.Pattern[str], text: str) -> int:
    if match := pattern.search(text):
        return int(match.group(1) or 1)
    return 0


def _weather(text: str) -> str:
    for keyword, weather in _WEATHER_MAP.items():
        if keyword in text:
            return weather
    return ""


def _buff_params(text: str, *, enemy: bool) -> dict[str, float]:
    result = {"atk": 0.0, "spatk": 0.0, "def": 0.0, "spdef": 0.0, "speed": 0.0}
    stat_map = {"物攻": "atk", "魔攻": "spatk", "物防": "def", "魔防": "spdef", "速度": "speed"}
    if enemy:
        for match in _RE_ENEMY_DOWN.finditer(text):
            result[stat_map[match.group(1)]] += int(match.group(2)) / 100.0
        return result
    for match in _RE_STAT_UP.finditer(text):
        result[stat_map[match.group(1)]] += int(match.group(2)) / 100.0
    for match in _RE_STAT_DOWN.finditer(text):
        result[stat_map[match.group(1)]] -= int(match.group(2)) / 100.0
    return result
