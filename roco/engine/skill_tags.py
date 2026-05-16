"""Skill sub-type classification — assigns tags from effect text + category.

Tags are assigned ONCE at parse/import time. At runtime, skill execution
dispatches to handlers based on tags — no regex in the hot path.

Tag taxonomy:
  pure_damage     — 纯伤害，无额外效果
  drain           — 吸血
  heal_hp         — 回复HP
  heal_energy     — 回复能量
  steal_energy    — 偷取敌方能量
  defense         — 减伤 (防御技能)
  burn            — 施加灼烧
  poison          — 施加中毒
  freeze          — 施加冻结
  leech           — 施加寄生
  counter         — 有应对效果
  stat_change     — 属性变化 (自身或敌方)
  force_switch    — 强制换人/折返
  charge          — 蓄力
  multi_hit       — 多段连击
  priority        — 先制攻击
  energy_all_in   — 全额投入
  weather         — 设置天气
  conditional     — 条件触发效果
  scaling         — 动态缩放 (基于HP/能量等)
"""

from __future__ import annotations

import re
from roco.engine.state import SkillRef

# ── Classification rules: (tag, pattern, field_to_set, value) ──

_CLASSIFIERS: list[tuple[str, str | None, str | None, object]] = [
    # (tag, effect_keyword, field_to_set_if_match, default_value)
    ("drain",         "吸血",     "life_drain",     0.5),
    ("heal_hp",       "回复",     "self_heal_hp",   0.5),   # refined below
    ("heal_energy",   None,       "self_heal_energy", 2),   # regex only
    ("steal_energy",  "偷取",     "steal_energy",    3),
    ("defense",       "减伤",     "damage_reduction", 0.7),
    ("burn",          "灼烧",     "burn_stacks",     1),
    ("poison",        "中毒",     "poison_stacks",   1),
    ("freeze",        "冻结",     "freeze_stacks",   1),
    ("leech",         "寄生",     "leech_stacks",    1),
    ("counter",       "应对",     None,              None),
    ("force_switch",  "折返",     "force_switch",    True),
    ("force_switch",  "强制换人", "force_switch",    True),
    ("charge",        "蓄力",     None,              None),
    ("multi_hit",     "连击",     "hit_count",       2),
    ("priority",      "先制",     "priority_mod",    1),
    ("priority",      "优先度",   "priority_mod",    1),
    ("energy_all_in", "耗尽",     None,              None),
    ("energy_all_in", "全额",     None,              None),
    ("weather",       "沙涌",     None,              None),
    ("weather",       "沙暴",     None,              None),
    ("weather",       "祈雨",     None,              None),
    ("weather",       "冰雹",     None,              None),
    ("weather",       "雪天",     None,              None),
    ("conditional",   "若敌方",   None,              None),
    ("conditional",   "若自身",   None,              None),
    ("conditional",   "每失去",   None,              None),
    ("scaling",       "每失去",   None,              None),
    ("scaling",       "每次使用", None,              None),
    ("mirror_damage", "反弹",     None,              None),
    ("mirror_damage", "反射",     None,              None),
    ("enemy_cost_up", "全技能能耗+", None,           None),
    ("hp_for_energy", "失去生命", None,              None),
    ("permanent_mod", "永久",     None,              None),
    ("permanent_mod", "每次使用后", None,            None),
    ("conditional_buff", "若敌方换人", None,         None),
    ("conditional_buff", "每层中毒", None,           None),
    ("burst",         "迸发",     "burst",           True),
    ("agility",       "迅捷",     "agility",         True),
    ("is_mark",       "印记",     "is_mark",         True),
]

# ── Regex-based refinements ──

_RE_HEAL_HP = re.compile(r"回复\s*(\d+)%\s*(HP|生命)")
_RE_HEAL_NRG = re.compile(r"回复\s*(\d+)\s*能量")
_RE_STEAL_NRG = re.compile(r"偷取\s*(\d+)\s*能量")
_RE_DRAIN_PCT = re.compile(r"吸血\s*(\d+)%")
_RE_DEF_PCT = re.compile(r"减伤\s*(\d+)%")
_RE_HIT_COUNT = re.compile(r"连击\s*(\d+)\s*次")
_RE_PRIO = re.compile(r"先制\s*\+?(-?\d+)")
_RE_BURN_N = re.compile(r"(\d+)\s*层\s*灼烧")
_RE_POISON_N = re.compile(r"(\d+)\s*层\s*中毒")
_RE_FREEZE_N = re.compile(r"(\d+)\s*层\s*冻结")
_RE_LEECH_N = re.compile(r"(\d+)\s*层\s*寄生")
_RE_COST_UP = re.compile(r"全技能能耗\s*\+\s*(\d+)")
_RE_HP_COST = re.compile(r"失去\s*(\d+)%\s*生命")
_RE_HIT_GROWTH = re.compile(r"连击数永久\s*\+\s*(\d+)")
_RE_POWER_GROWTH = re.compile(r"威力永久\s*\+\s*(\d+)")
_WEATHER_MAP = {"沙涌": "sandstorm", "沙暴": "sandstorm", "祈雨": "rain", "求雨": "rain",
                "冰雹": "snow", "雪天": "snow", "暴风雪": "snow"}
_RE_STAT_UP = re.compile(r"(物攻|魔攻|物防|魔防|速度)\s*\+(\d+)%")
_RE_STAT_DOWN = re.compile(r"(物攻|魔攻|物防|魔防|速度)\s*\-(\d+)%")
_RE_ENEMY_DOWN = re.compile(r"敌方(物攻|魔攻|物防|魔防|速度)\s*\-(\d+)%")


def _stat_field(name: str, prefix: str = "self_") -> str:
    """Map Chinese stat name → SkillRef field name."""
    m = {"物攻": "atk", "魔攻": "spatk", "物防": "def", "魔防": "spdef", "速度": "speed"}
    return prefix + m.get(name, name)


def classify(skill: SkillRef) -> SkillRef:
    """Classify a skill and assign effect_flags + numeric fields."""
    from roco.engine.state import EffectFlag
    eff = skill.effect
    flags = EffectFlag.NONE
    _tag_to_flag: dict[str, EffectFlag] = {f.name.lower(): f for f in EffectFlag if f.name != "NONE"}

    for tag, keyword, field, default in _CLASSIFIERS:
        if keyword and keyword in eff:
            flag = _tag_to_flag.get(tag)
            if flag:
                flags |= flag
            if field and default is not None and getattr(skill, field) == 0:
                setattr(skill, field, default)

    # ── Refine numeric values with regex ──

    if m := _RE_DRAIN_PCT.search(eff):
        skill.life_drain = int(m.group(1)) / 100.0

    if m := _RE_HEAL_HP.search(eff):
        skill.self_heal_hp = int(m.group(1)) / 100.0
        if not (flags & EffectFlag.HEAL_HP):
            flags |= EffectFlag.HEAL_HP

    if m := _RE_HEAL_NRG.search(eff):
        skill.self_heal_energy = int(m.group(1))
        if not (flags & EffectFlag.HEAL_ENERGY):
            flags |= EffectFlag.HEAL_ENERGY
    if m := _RE_STEAL_NRG.search(eff):
        skill.steal_energy = int(m.group(1))

    if m := _RE_DEF_PCT.search(eff):
        skill.damage_reduction = int(m.group(1)) / 100.0

    if m := _RE_HIT_COUNT.search(eff):
        skill.hit_count = int(m.group(1))

    if m := _RE_PRIO.search(eff):
        skill.priority_mod = int(m.group(1))

    if m := _RE_BURN_N.search(eff):
        skill.burn_stacks = int(m.group(1))
    if m := _RE_POISON_N.search(eff):
        skill.poison_stacks = int(m.group(1))
    if m := _RE_FREEZE_N.search(eff):
        skill.freeze_stacks = int(m.group(1))
    if m := _RE_LEECH_N.search(eff):
        skill.leech_stacks = int(m.group(1))

    # Stat changes
    for m in _RE_STAT_UP.finditer(eff):
        field = _stat_field(m.group(1))
        pct = int(m.group(2)) / 100.0
        setattr(skill, field, getattr(skill, field, 0) + pct)
        if not (flags & EffectFlag.STAT_CHANGE):
            flags |= EffectFlag.STAT_CHANGE
    for m in _RE_STAT_DOWN.finditer(eff):
        field = _stat_field(m.group(1))
        pct = -int(m.group(2)) / 100.0
        cur = getattr(skill, field, 0)
        if cur == 0:
            setattr(skill, field, pct)
        if not (flags & EffectFlag.STAT_CHANGE):
            flags |= EffectFlag.STAT_CHANGE
    for m in _RE_ENEMY_DOWN.finditer(eff):
        field = _stat_field(m.group(1), "enemy_")
        pct = int(m.group(2)) / 100.0
        setattr(skill, field, pct)
        if not (flags & EffectFlag.STAT_CHANGE):
            flags |= EffectFlag.STAT_CHANGE

    # ── Parse weather type ──
    for kw, wt in _WEATHER_MAP.items():
        if kw in eff:
            skill.weather_type = wt
            if not (flags & EffectFlag.WEATHER):
                flags |= EffectFlag.WEATHER
            break

    # ── Parse numeric effect values ──
    if m := _RE_COST_UP.search(eff):
        skill.enemy_cost_up_amount = int(m.group(1))
    if m := _RE_HP_COST.search(eff):
        skill.hp_cost_pct = int(m.group(1)) / 100.0
    if m := _RE_HIT_GROWTH.search(eff):
        skill.permanent_hit_growth = int(m.group(1))
        if not (flags & EffectFlag.PERMANENT_MOD):
            flags |= EffectFlag.PERMANENT_MOD
    if m := _RE_POWER_GROWTH.search(eff):
        skill.permanent_power_growth = int(m.group(1))
        if not (flags & EffectFlag.PERMANENT_MOD):
            flags |= EffectFlag.PERMANENT_MOD

    # ── Ability tag classification ──
    if "应对" in eff and not (flags & EffectFlag.COUNTER):
        flags |= EffectFlag.COUNTER

    # Pure damage: no other tags assigned
    if flags == EffectFlag.NONE and skill.power > 0:
        flags |= EffectFlag.PURE_DAMAGE

    skill.effect_flags = flags
    return skill
