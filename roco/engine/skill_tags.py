"""Import-time skill text classification into compact flags only."""

from __future__ import annotations

import re

from roco.engine.effect_model import EffectFlag
from roco.engine.enums import SkillCategory
from roco.engine.state import SkillData


_RE_HIT_COUNT = re.compile(r"(?:连击\s*(\d+)\s*次|(\d+)\s*连击)")
_RE_PRIO = re.compile(r"先制\s*\+?(-?\d+)")


def classify(skill: SkillData) -> SkillData:
    """Assign compact flags, hit count, and priority without runtime effect fields."""
    skill.category = _normalize_category(skill.category)
    text = skill.effect
    flags = EffectFlag.NONE

    if skill.power > 0 or "造成物伤" in text or "造成魔伤" in text or "造成物理伤害" in text or "造成魔法伤害" in text:
        flags |= EffectFlag.PURE_DAMAGE
    if "吸血" in text:
        flags |= EffectFlag.DRAIN
    if "回复" in text:
        flags |= EffectFlag.HEAL_HP
    if "能量" in text and ("回复" in text or "偷取" in text or "失去" in text):
        flags |= EffectFlag.HEAL_ENERGY
    if "偷取" in text and "能量" in text:
        flags |= EffectFlag.STEAL_ENERGY
    if "减伤" in text:
        flags |= EffectFlag.DEFENSE
    if "灼烧" in text:
        flags |= EffectFlag.BURN
    if "中毒" in text:
        flags |= EffectFlag.POISON
    if "冻结" in text:
        flags |= EffectFlag.FREEZE
    if "寄生" in text:
        flags |= EffectFlag.LEECH
    if "应对" in text:
        flags |= EffectFlag.COUNTER
    if "折返" in text or "强制换人" in text:
        flags |= EffectFlag.FORCE_SWITCH
    if "蓄力" in text:
        flags |= EffectFlag.CHARGE
    if "沙涌" in text or "沙暴" in text or "祈雨" in text or "求雨" in text or "冰雹" in text or "雪天" in text:
        flags |= EffectFlag.WEATHER
    if "耗尽" in text or "全额" in text:
        flags |= EffectFlag.ENERGY_ALL_IN
    if "永久" in text or "每次使用后" in text:
        flags |= EffectFlag.PERMANENT_MOD
    if "迸发" in text:
        flags |= EffectFlag.BURST
    if "迅捷" in text:
        flags |= EffectFlag.AGILITY
    if "印记" in text:
        flags |= EffectFlag.IS_MARK
    if "奉献" in text:
        flags |= EffectFlag.DEVOTION

    if match := _RE_HIT_COUNT.search(text):
        skill.hit_count = int(match.group(1) or match.group(2))
    if match := _RE_PRIO.search(text):
        skill.priority_mod = int(match.group(1))

    skill.effect_flags = flags
    return skill


def _normalize_category(raw: object) -> SkillCategory:
    if isinstance(raw, SkillCategory):
        return raw
    mapping = {
        "物攻": SkillCategory.PHYSICAL,
        "魔攻": SkillCategory.MAGICAL,
        "防御": SkillCategory.DEFENSE,
        "状态": SkillCategory.STATUS,
    }
    return mapping.get(str(raw or "").strip(), SkillCategory.PHYSICAL)
