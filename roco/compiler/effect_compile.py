"""Compile canonical skill text into immutable runtime effect rows."""

from __future__ import annotations

import re
from types import MappingProxyType

from roco.compiler.effect_model import EffectFlag, EffectSpec, EffectTag, SkillEffect, Timing
from roco.compiler.records import SkillData


_RE_HEAL_HP = re.compile(r"回复\s*(\d+)%\s*(?:HP|生命)")
_RE_HEAL_NRG = re.compile(r"回复\s*(\d+)\s*能量")
_RE_STEAL_NRG = re.compile(r"偷取(?:敌方)?\s*(\d+)\s*能量")
_RE_ENEMY_LOSE_NRG = re.compile(r"敌方失去\s*(\d+)\s*能量")
_RE_DRAIN_PCT = re.compile(r"吸血\s*(\d+)%")
_RE_DRAIN_PCT_PREFIX = re.compile(r"(\d+)%\s*吸血")
_RE_DEF_PCT = re.compile(r"减伤\s*(\d+)%")
_RE_HIT_COUNT = re.compile(r"(?:连击\s*(\d+)\s*次|(\d+)\s*连击)")
_RE_BURN_N = re.compile(r"(\d+)?\s*层?\s*灼烧")
_RE_POISON_N = re.compile(r"(\d+)?\s*层?\s*中毒(?!印记)")
_RE_FREEZE_N = re.compile(r"(\d+)?\s*层?\s*冻结")
_RE_LEECH_N = re.compile(r"(\d+)?\s*层?\s*寄生")
_RE_COST_UP = re.compile(r"全技能能耗\s*\+\s*(\d+)")
_RE_ENEMY_CURRENT_COST_UP = re.compile(r"敌方本回合使用的技能能耗\+(\d+)，持续(\d+)回合")
_RE_ENEMY_OTHER_COST_UP = re.compile(r"敌方除本回合使用的技能，其他技能能耗\+(\d+)，持续(\d+)回合")
_RE_PASSIVE_COST_REDUCE = re.compile(r"(?:本技能)?(?:被动)?(?:额外)?-?(\d+)能耗|能耗-(\d+)")
_RE_HP_COST = re.compile(r"失去\s*(\d+)%\s*生命")
_RE_HIT_GROWTH = re.compile(r"连击数永久\s*\+\s*(\d+)")
_RE_POWER_GROWTH = re.compile(r"威力永久\s*\+\s*(\d+)")
_RE_HIT_DELTA = re.compile(r"连击数\s*\+\s*(\d+)")
_RE_POWER_DELTA = re.compile(r"(?:全技能)?威力\s*\+\s*(\d+)(?!%)")
_RE_FLAT_SPEED = re.compile(r"速度\s*\+\s*(\d+)(?!%)")
_STAT_WORD = r"(物攻|魔攻|双攻|物防|魔防|双防|攻防|速度)"
_RE_STAT_UP = re.compile(_STAT_WORD + r"\s*\+(\d+)%")
_RE_STAT_DOWN = re.compile(_STAT_WORD + r"\s*\-(\d+)%")
_RE_ENEMY_DOWN = re.compile(r"敌方" + _STAT_WORD + r"\s*\-(\d+)%")
_RE_ENEMY_FLAT_DOWN = re.compile(r"敌方获得" + _STAT_WORD + r"\s*\-(\d+)")
_WEATHER_MAP = {
    "沙涌": "sandstorm",
    "沙暴": "sandstorm",
    "祈雨": "rain",
    "求雨": "rain",
    "雨天": "rain",
    "冰雹": "snow",
    "雪天": "snow",
    "暴风雪": "snow",
    "落雨": "rain",
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
    if match := _RE_DRAIN_PCT.search(text) or _RE_DRAIN_PCT_PREFIX.search(text):
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
    if "驱散敌方所有增益" in text or "驱散目标所有增益" in text:
        add(Timing.AFTER_MOVE, EffectTag.DISPEL_BUFFS, {"target": "enemy"}, order); order += 1
    if "驱散自己的减益" in text or "驱散自己减益" in text:
        add(Timing.AFTER_MOVE, EffectTag.CLEANSE, {"target": "self"}, order); order += 1

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
    if "每回合随机变成己方队伍中其他精灵的技能" in text:
        add(Timing.PASSIVE, EffectTag.BORROW_TEAM_SKILL, {}, order); order += 1
    if "与敌方交换携带的技能" in text:
        add(Timing.AFTER_MOVE, EffectTag.EXCHANGE_MOVES, {}, order); order += 1
    if "与敌方交换增益和减益" in text:
        add(Timing.AFTER_MOVE, EffectTag.TRANSFER_MODS, {}, order); order += 1
    if "与敌方交换生命比例" in text:
        add(Timing.AFTER_MOVE, EffectTag.EXCHANGE_HP_RATIO, {}, order); order += 1
    if "回复生命，改为失去2倍" in text:
        add(Timing.AFTER_MOVE, EffectTag.ANTI_HEAL, {"multiplier": 2}, order); order += 1
    if "耗尽" in text or "全额" in text:
        add(Timing.BEFORE_MOVE, EffectTag.ENERGY_ALL_IN, {}, order); order += 1
    if weather := _weather(text):
        add(Timing.AFTER_MOVE, EffectTag.WEATHER, {"type": weather, "turns": _weather_turns(text)}, order); order += 1

    self_buff = _buff_params(text, enemy=False)
    if any(self_buff.values()):
        add(Timing.AFTER_MOVE, EffectTag.SELF_BUFF, self_buff, order); order += 1
    enemy_debuff = _buff_params(text, enemy=True)
    if any(enemy_debuff.values()):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_DEBUFF, enemy_debuff, order); order += 1

    if match := _RE_COST_UP.search(text):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_ENERGY_COST_UP, {"amount": int(match.group(1)), "turns": 3}, order); order += 1
    if match := _RE_ENEMY_CURRENT_COST_UP.search(text):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_ENERGY_COST_UP, {"amount": int(match.group(1)), "turns": int(match.group(2)), "scope": "current_skill"}, order); order += 1
    if match := _RE_ENEMY_OTHER_COST_UP.search(text):
        add(Timing.AFTER_MOVE, EffectTag.ENEMY_ENERGY_COST_UP, {"amount": int(match.group(1)), "turns": int(match.group(2)), "scope": "other_skills"}, order); order += 1
    if match := _RE_PASSIVE_COST_REDUCE.search(text):
        add(Timing.BEFORE_MOVE, EffectTag.PASSIVE_ENERGY_REDUCE, {"amount": int(match.group(1) or match.group(2))}, order); order += 1
    if match := _RE_HP_COST.search(text):
        add(Timing.BEFORE_MOVE, EffectTag.HP_FOR_ENERGY, {"pct": int(match.group(1)) / 100.0}, order); order += 1
    if match := _RE_HIT_GROWTH.search(text):
        add(Timing.AFTER_MOVE, EffectTag.PERMANENT_MOD, {"target": "hit_count", "delta": int(match.group(1))}, order); order += 1
    if match := _RE_POWER_GROWTH.search(text):
        add(Timing.AFTER_MOVE, EffectTag.PERMANENT_MOD, {"target": "power", "delta": int(match.group(1))}, order); order += 1
    elif match := _RE_POWER_DELTA.search(text):
        add(Timing.AFTER_MOVE, EffectTag.NEXT_ATTACK_MOD, {"power_bonus": int(match.group(1))}, order); order += 1
    if match := _RE_HIT_DELTA.search(text):
        add(Timing.AFTER_MOVE, EffectTag.PERMANENT_MOD, {"target": "hit_count", "delta": int(match.group(1))}, order); order += 1
    if match := _RE_FLAT_SPEED.search(text):
        add(Timing.AFTER_MOVE, EffectTag.SELF_BUFF, {"speed": int(match.group(1)) / 100.0}, order); order += 1
    if "敌方获得1层萌化" in text or "敌方获得萌化" in text:
        add(Timing.AFTER_MOVE, EffectTag.CUTE_ENEMY_GAIN, {"stacks": 1}, order); order += 1
    if match := re.search(r"敌方获得连击数-(\d+)", text):
        add(Timing.AFTER_MOVE, EffectTag.HIT_COUNT_DELTA, {"target": "enemy", "delta": -int(match.group(1))}, order); order += 1
    if "自己获得萌化" in text or "自身获得萌化" in text:
        add(Timing.AFTER_MOVE, EffectTag.CUTE_GAIN, {"stacks": 1}, order); order += 1
    if "将自己的萌化转移给敌方" in text or "解除萌化" in text:
        add(Timing.AFTER_MOVE, EffectTag.CUTE_TRANSFER, {}, order); order += 1
    if "自己和敌方" in text and "萌化" in text:
        add(Timing.AFTER_MOVE, EffectTag.CUTE_BOTH, {"stacks": 1}, order); order += 1
    if "脱离" in text:
        add(Timing.AFTER_MOVE, EffectTag.FORCE_SWITCH, {}, order); order += 1
    if "敌方精灵返场" in text or "使敌方精灵返场" in text:
        add(Timing.AFTER_MOVE, EffectTag.FORCE_ENEMY_SWITCH, {}, order); order += 1
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


def _weather_turns(text: str) -> int:
    if match := re.search(r"持续(\d+)回合", text):
        return int(match.group(1))
    return 5


def _buff_params(text: str, *, enemy: bool) -> dict[str, float]:
    result = {"atk": 0.0, "spatk": 0.0, "def": 0.0, "spdef": 0.0, "speed": 0.0}
    stat_map = {
        "物攻": ("atk",),
        "魔攻": ("spatk",),
        "双攻": ("atk", "spatk"),
        "物防": ("def",),
        "魔防": ("spdef",),
        "双防": ("def", "spdef"),
        "攻防": ("atk", "spatk", "def", "spdef"),
        "速度": ("speed",),
    }
    if enemy:
        for match in _RE_ENEMY_DOWN.finditer(text):
            for key in stat_map[match.group(1)]:
                result[key] += int(match.group(2)) / 100.0
        for match in _RE_ENEMY_FLAT_DOWN.finditer(text):
            for key in stat_map[match.group(1)]:
                result[key] += int(match.group(2)) / 100.0
        return result
    for match in _RE_STAT_UP.finditer(text):
        for key in stat_map[match.group(1)]:
            result[key] += int(match.group(2)) / 100.0
    for match in _RE_STAT_DOWN.finditer(text):
        for key in stat_map[match.group(1)]:
            result[key] -= int(match.group(2)) / 100.0
    return result
