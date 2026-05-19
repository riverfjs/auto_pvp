"""Ability text rules that generate canonical effect rows."""

from __future__ import annotations

import re

from roco.compiler.classifiers.common import EffectRecord, dedupe

_ABILITY_PATTERNS: tuple[tuple[re.Pattern[str], EffectRecord], ...] = (
    (re.compile(r"力竭.*不扣MP|不扣MP"), {"timing": "PASSIVE", "tag": "FAINT_NO_MP_LOSS", "params": {}}),
    (re.compile(r"先于敌方.*威力\+?(\d+)%"), {"timing": "CALC_DAMAGE", "tag": "FIRST_STRIKE_POWER_BONUS", "params": {"bonus_pct": 0.5}}),
    (re.compile(r"每回合.*(?:回复|获得|增加)(\d+)能量|每回合能量\+(\d+)"), {"timing": "TURN_END", "tag": "ENERGY_REGEN_PER_TURN", "params": {"amount": 1}}),
    (re.compile(r"灼烧.*不(?:会)?衰减|灼烧不衰减"), {"timing": "PASSIVE", "tag": "BURN_NO_DECAY", "params": {}}),
    (re.compile(r"中毒.*额外(?:结算|伤害)|额外.*中毒"), {"timing": "PASSIVE", "tag": "EXTRA_POISON_TICK", "params": {}}),
    (re.compile(r"额外.*冻结|冻结.*额外"), {"timing": "PASSIVE", "tag": "EXTRA_FREEZE_ON_FREEZE", "params": {"extra": 2}}),
)


def generated_ability_effects(description: str) -> tuple[EffectRecord, ...]:
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
    _append_damage_rules(rows, description)
    _append_passive_rules(rows, description)
    _append_lifecycle_rules(rows, description)
    _append_skill_reaction_rules(rows, description)
    _append_entry_rules(rows, description)
    _append_counter_and_combo_rules(rows, description)
    _append_generic_rules(rows, description)
    return tuple(dedupe(rows))


def _append_damage_rules(rows: list[EffectRecord], description: str) -> None:
    if match := re.search(r"携带的[【「]([^】」]+)[】」]技能威力\+(\d+)", description):
        rows.append({
            "timing": "CALC_DAMAGE",
            "tag": "SPECIFIC_SKILL_POWER_BONUS",
            "params": {"skill": match.group(1), "power_bonus": int(match.group(2))},
        })
    if match := re.search(r"己方精灵每使用1次状态技能，?自己入场时(.+?)技能威力\+(\d+)", description):
        rows.append({
            "timing": "CALC_DAMAGE",
            "tag": "POWER_BY_STATUS_COUNT_ELEMENTS",
            "params": {"elements": _element_words(match.group(1)), "power_bonus": int(match.group(2))},
        })
    if match := re.search(r"携带的能耗为(\d+)的技能，?威力\+(\d+)%", description):
        rows.append({
            "timing": "CALC_DAMAGE",
            "tag": "LOW_COST_SKILL_POWER_BONUS",
            "params": {"cost_threshold": int(match.group(1)), "bonus_pct": int(match.group(2)) / 100.0},
        })
    if match := re.search(r"非光系技能威力\+(\d+)%|非光系技能，?威力\+(\d+)%", description):
        value = int(match.group(1) or match.group(2))
        rows.append({"timing": "CALC_DAMAGE", "tag": "DAMAGE_MOD_NON_LIGHT", "params": {"bonus_pct": value / 100.0}})
    if match := re.search(r"非本系.*威力\+(\d+)%|非敌方系别.*威力\+(\d+)%", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "DAMAGE_MOD_NON_STAB", "params": {"bonus_pct": int(match.group(1)) / 100.0}})
    if "首领血脉" in description and "威力" in description:
        rows.append({"timing": "CALC_DAMAGE", "tag": "DAMAGE_MOD_LEADER_BLOOD", "params": {"bonus_pct": 1.0}})
    if "污染血脉" in description and "威力" in description:
        rows.append({"timing": "CALC_DAMAGE", "tag": "DAMAGE_MOD_POLLUTANT_BLOOD", "params": {"bonus_pct": 1.0}})
    if match := re.search(r"携带的攻击技能获得迸发：威力\+(\d+)", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "POWER_DYNAMIC", "params": {"bonus": int(match.group(1))}})
    if match := re.search(r"携带的能耗小于(\d+)的技能，?获得迅捷", description):
        rows.append({"timing": "PASSIVE", "tag": "SKILL_MOD", "params": {"slots": [0, 1, 2, 3], "priority": 1}})
    if match := re.search(r"携带的" + _ELEMENT_WORD + r"系技能获得迅捷", description):
        rows.append({"timing": "PASSIVE", "tag": "SKILL_MOD", "params": {"slots": [0, 1, 2, 3], "priority": 1}})
    if match := re.search(r"携带的(防御|状态|攻击|物攻|魔攻)技能能耗-(\d+)", description):
        category = {"防御": "防御", "状态": "状态", "攻击": "attack", "物攻": "physical", "魔攻": "magical"}[match.group(1)]
        rows.append({"timing": "BEFORE_MOVE", "tag": "CARRY_SKILL_COST_REDUCE", "params": {"category": category, "reduce": int(match.group(2))}})
    if match := re.search(r"携带的能耗小于等于(\d+)的攻击技能，?威力\+(\d+)%", description):
        rows.append({
            "timing": "CALC_DAMAGE",
            "tag": "LOW_COST_SKILL_POWER_BONUS",
            "params": {"cost_threshold": int(match.group(1)), "bonus_pct": int(match.group(2)) / 100.0},
        })


def _append_passive_rules(rows: list[EffectRecord], description: str) -> None:
    if "赋予的印记不会替换其他印记" in description:
        rows.append({"timing": "PASSIVE", "tag": "MARK_STACK_NO_REPLACE", "params": {}})
    if "回合开始时" in description and "技能顺序打乱" in description:
        rows.append({"timing": "PASSIVE", "tag": "SHUFFLE_SKILLS_REDUCE_LAST", "params": {}})
    if "蓄力状态下，可以使用任一携带技能" in description:
        rows.append({"timing": "PASSIVE", "tag": "CHARGE_FREE_SKILL", "params": {}})
    if "触发星陨时消耗一半层数" in description or ("触发星陨印记" in description and "消耗一半层数" in description):
        rows.append({"timing": "PASSIVE", "tag": "HALF_METEOR_FULL_DAMAGE", "params": {}})
    if match := re.search(r"获得增益时，?额外获得层数\+(\d+)", description):
        rows.append({"timing": "PASSIVE", "tag": "BUFF_EXTRA_LAYERS", "params": {"layers": int(match.group(1))}})
    if "获得能量或生命时" in description and "场下" in description:
        rows.append({"timing": "PASSIVE", "tag": "SHARE_GAINS", "params": {}})
    if match := re.search(r"每回复1能量，?同时回复(\d+)%生命", description):
        rows.append({"timing": "PASSIVE", "tag": "HEAL_HP_PER_ENERGY_GAIN", "params": {"pct": int(match.group(1)) / 100.0}})
    if match := re.search(r"自己技能的迸发效果延长(\d+)回合", description):
        rows.append({"timing": "PASSIVE", "tag": "BURST_EXTEND", "params": {"turns": int(match.group(1))}})
    if "能量不足" in description and "5%生命" in description:
        rows.append({"timing": "PASSIVE", "tag": "HP_FOR_ENERGY", "params": {"pct": 0.05}})
    if "能量可超上限" in description or "能量不受上限" in description or "超过能量上限" in description or "突破能量上限" in description:
        rows.append({"timing": "PASSIVE", "tag": "ENERGY_NO_CAP", "params": {}})
    if "能耗增加变为能耗降低" in description and "能耗降低变为能耗增加" in description:
        rows.append({"timing": "PASSIVE", "tag": "COST_INVERT", "params": {}})
    if "额外损失1点魔力" in description:
        rows.append({"timing": "PASSIVE", "tag": "KILL_MP_PENALTY", "params": {}})
    if "仅可以使用1号位技能" in description:
        rows.append({"timing": "PASSIVE", "tag": "SKILL_SLOT_LOCK", "params": {}})
    if "触发次数-1" in description:
        rows.append({"timing": "PASSIVE", "tag": "TURN_END_SKIP", "params": {}})
    if "增益和减益会被更换入场的精灵继承" in description:
        rows.append({"timing": "PASSIVE", "tag": "COPY_SWITCH_STATE", "params": {}})
    if "受到灼烧伤害时，自己回复等量生命" in description:
        rows.append({"timing": "PASSIVE", "tag": "HEAL_ON_BURN_DAMAGE", "params": {}})
    if "受到中毒效果伤害时，自己回复等量生命" in description:
        rows.append({"timing": "PASSIVE", "tag": "HEAL_ON_POISON_DAMAGE", "params": {}})
    if "可获得的萌化层数不受限制" in description:
        rows.append({"timing": "PASSIVE", "tag": "CUTE_NO_CAP", "params": {}})
    if "能量等于0" in description and "无法对自己造成伤害" in description:
        rows.append({"timing": "PASSIVE", "tag": "IMMUNE_ZERO_ENERGY_ATTACKER", "params": {}})
    if "能耗小于等于1的攻击技能" in description and "无法对自己造成伤害" in description:
        rows.append({"timing": "PASSIVE", "tag": "IMMUNE_LOW_COST_ATTACK", "params": {}})
    if "连击数固定为2" in description:
        rows.append({"timing": "PASSIVE", "tag": "FIXED_HIT_COUNT_ALL", "params": {}})
    if "受到致命伤害" in description and "萌化" in description:
        rows.append({"timing": "PASSIVE", "tag": "CUTE_LETHAL_SHIELD", "params": {"stacks": 1}})
    if "技能每回合位置变化时" in description and "能耗-1" in description:
        rows.append({"timing": "BEFORE_MOVE", "tag": "PASSIVE_ENERGY_REDUCE", "params": {"amount": 1}})
    if "初始能量为0" in description:
        rows.append({"timing": "PASSIVE", "tag": "START_ZERO_ENERGY", "params": {}})


def _append_lifecycle_rules(rows: list[EffectRecord], description: str) -> None:
    if "入场时，复制敌方的增益" in description:
        rows.append({"timing": "SWITCH_IN", "tag": "MIRROR_ENEMY_BUFFS", "params": {}})
    if "根据捕捉所用的咕噜球" in description:
        rows.append({"timing": "SWITCH_IN", "tag": "CONTRACT_ENTRY", "params": {"ball": "绝缘球", "speed": 0.5, "poison": 1}})
    if match := re.search(r"回合结束时.*(?:回复|获得)(\d+)能量", description):
        rows.append({"timing": "TURN_END", "tag": "HEAL_ENERGY", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"离场时回复(\d+)能量", description):
        rows.append({"timing": "SWITCH_OUT", "tag": "LEAVE_ENERGY_REFILL", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"离场后，?更换入场的精灵回复(\d+)%生命", description):
        rows.append({"timing": "SWITCH_OUT", "tag": "LEAVE_HEAL_ALLY", "params": {"pct": int(match.group(1)) / 100.0}})
    if match := re.search(r"敌方精灵离场时，?自己获得全技能能耗-(\d+)", description):
        rows.append({"timing": "ENEMY_SWITCH", "tag": "ENEMY_SWITCH_SELF_COST_REDUCE", "params": {"reduce": int(match.group(1))}})
    if match := re.search(r"敌方精灵离场后，?更换入场的精灵失去(\d+)能量", description):
        rows.append({"timing": "ENEMY_SWITCH", "tag": "ENEMY_LOSE_ENERGY", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"偷取敌方(?:场上)?(?:所有)?精灵?(\d+)能量|偷取所有敌方精灵(\d+)能量", description):
        rows.append({"timing": "TURN_END", "tag": "STEAL_ALL_ENEMY_ENERGY", "params": {"amount": int(match.group(1) or match.group(2))}})
    if "偷取" in description and "印记" in description:
        rows.append({"timing": "TURN_END", "tag": "STEAL_MARKS", "params": {}})
    if match := re.search(r"敌方获得(\d+)层星陨印记", description):
        rows.append({"timing": "TURN_END", "tag": "METEOR_MARK", "params": {"target": "enemy", "stacks": int(match.group(1))}})
    if "每次行动后脱离" in description:
        rows.append({"timing": "AFTER_MOVE", "tag": "AUTO_SWITCH_AFTER_ACTION", "params": {}})
    if "敌方每2层中毒转化为1层中毒印记" in description:
        rows.append({"timing": "TURN_END", "tag": "CONVERT_POISON_TO_MARK", "params": {}})
    if "回合结束时" in description and ("能量为0" in description or "能量等于0" in description) and ("脱离" in description or "替换" in description):
        rows.append({"timing": "TURN_END", "tag": "AUTO_SWITCH_ON_ZERO_ENERGY", "params": {}})


def _append_skill_reaction_rules(rows: list[EffectRecord], description: str) -> None:
    if match := re.search(r"入场后首次行动，?所选技能使用次数\+(\d+)", description):
        rows.append({"timing": "PASSIVE", "tag": "FIRST_ACTION_EXTRA_USE", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"每次进入蓄力状态，?获得全技能能耗永久-(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "CHARGE_COST_REDUCE", "params": {"reduce": int(match.group(1))}})
    if match := re.search(r"攻击会使敌方已有的减益层数\+(\d+)", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "DEBUFF_EXTRA_LAYERS", "params": {"layers": int(match.group(1))}})
    if "若使用技能能耗高于敌方" in description and "敌方失去能耗之差的能量" in description:
        rows.append({"timing": "AFTER_MOVE", "tag": "ENERGY_DRAIN_BY_COST_DIFF", "params": {}})
    if "使用状态技能后" in description and "聒噪" in description:
        rows.append({
            "timing": "AFTER_MOVE",
            "tag": "ENEMY_ENERGY_COST_UP",
            "params": {"amount": 3, "turns": 3, "scope": "attack", "requires_skill_category": "status"},
        })
    if match := re.search(r"获得冻结时.*全技能能耗\+(\d+)", description):
        rows.append({
            "timing": "AFTER_MOVE",
            "tag": "ENEMY_ENERGY_COST_UP",
            "params": {"amount": int(match.group(1)), "turns": 3, "scope": "all", "trigger": "inflict_freeze"},
        })
    if match := re.search(r"使用后使敌方获得(\d+)层灼烧", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "BURN", "params": {"target": "enemy", "stacks": int(match.group(1))}})
    if "每受到1次攻击" in description and "50威力物理伤害" in description:
        rows.append({"timing": "TAKE_DAMAGE", "tag": "COUNTER_ATTACK", "params": {"power": 50}})
    if "被攻击时" in description and "棘刺印记" in description:
        stacks = 1
        if match := re.search(r"赋予敌方(\d+)层棘刺印记", description):
            stacks = int(match.group(1))
        rows.append({"timing": "TAKE_DAMAGE", "tag": "THORN_MARK", "params": {"target": "enemy", "stacks": stacks}})
    if "打断敌方时" in description and "2回合冷却" in description:
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_INTERRUPT_COOLDOWN", "params": {"turns": 2}})
    if match := re.search(r"携带的" + _ELEMENT_WORD + r"系技能获得迸发：能耗-(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "ON_SKILL_ELEMENT_COST_REDUCE", "params": {"element": match.group(1), "reduce": int(match.group(2))}})
    if match := re.search(r"攻击技能获得迸发：敌方获得全技能能耗\+(\d+)", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ENEMY_ENERGY_COST_UP", "params": {"amount": int(match.group(1)), "turns": 3, "scope": "all", "requires_skill_category": "attack"}})
    if match := re.search(r"在场时，敌方全技能能耗\+(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "ENEMY_ALL_COST_UP", "params": {"amount": int(match.group(1)), "turns": 1}})
    if match := re.search(r"使用" + _ELEMENT_WORD + r"系技能后，?获得双攻\+(\d+)%", description):
        bonus = int(match.group(2)) / 100.0
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_BUFF", "params": {"element": match.group(1), "buff": {"atk": bonus, "spatk": bonus}}})
    if match := re.search(r"(?:释放|使用)" + _ELEMENT_WORD + r"系技能后，?物攻永久提升(\d+)%[，,]速度永久-(\d+)", description):
        rows.append({
            "timing": "AFTER_MOVE",
            "tag": "ON_SKILL_ELEMENT_BUFF",
            "params": {
                "element": match.group(1),
                "buff": {"atk": int(match.group(2)) / 100.0, "speed": -int(match.group(3)) / 100.0},
            },
        })
    if match := re.search(r"使用草系技能后，?回复(\d+)%生命", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "HEAL_ON_GRASS_SKILL", "params": {"heal_pct": int(match.group(1)) / 100.0}})
    if match := re.search(r"使用" + _ELEMENT_WORD + r"系技能(?:后|时)，?敌方获得(\d*)层?中毒", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_POISON", "params": {"element": match.group(1), "stacks": int(match.group(2) or 1)}})
    if match := re.search(_ELEMENT_WORD + r"系技能使敌方获得(\d*)层?中毒", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_POISON", "params": {"element": match.group(1), "stacks": int(match.group(2) or 1)}})
    if match := re.search(_ELEMENT_WORD + r"系技能使敌方获得(\d*)层?灼烧", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_BURN", "params": {"element": match.group(1), "stacks": int(match.group(2) or 1)}})
    if match := re.search(_ELEMENT_WORD + r"系技能使敌方获得(\d*)层?冻结", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_FREEZE", "params": {"element": match.group(1), "stacks": int(match.group(2) or 1)}})
    if match := re.search(r"使用" + _ELEMENT_WORD + r"系技能后，?全技能能耗-(\d+)", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_COST_REDUCE", "params": {"element": match.group(1), "reduce": int(match.group(2))}})
    if match := re.search(_ELEMENT_WORD + r"系技能能耗-(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "ON_SKILL_ELEMENT_COST_REDUCE", "params": {"element": match.group(1), "reduce": int(match.group(2))}})
    if match := re.search(r"使用" + _ELEMENT_WORD + r"系技能后，?敌方失去(\d+)能量", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "ON_SKILL_ELEMENT_ENEMY_ENERGY", "params": {"element": match.group(1), "amount": int(match.group(2))}})
    if match := re.search(r"使用能耗小于等于(\d+)的技能时，?敌方获得(\d+)层中毒", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "POISON_ON_SKILL_APPLY", "params": {"cost_threshold": int(match.group(1)), "stacks": int(match.group(2))}})


def _append_entry_rules(rows: list[EffectRecord], description: str) -> None:
    if match := re.search(r"己方其他精灵每有1层萌化，?自己入场时全技能能耗-(\d+)", description):
        rows.append({"timing": "SWITCH_IN", "tag": "CUTE_BENCH_COST_REDUCE", "params": {"reduce": int(match.group(1))}})
    if match := re.search(r"队伍中每有1只其他的虫系精灵，?自己入场时获得攻防速\+(\d+)%", description):
        rows.append({"timing": "SWITCH_IN", "tag": "TEAM_SYNERGY_BUG_SWARM_ATTACK", "params": {"bonus_pct": int(match.group(1)) / 100.0}})
    if "首次入场时" in description and "一半的当前生命" in description:
        rows.append({"timing": "SWITCH_IN", "tag": "ENTRY_SELF_DAMAGE", "params": {"pct_current": 0.5}})
    if match := re.search(r"入场时获得(\d+)%吸血", description):
        rows.append({"timing": "SWITCH_IN", "tag": "GRANT_LIFE_DRAIN", "params": {"pct": int(match.group(1)) / 100.0}})
    if match := re.search(r"立即回复(\d+)能量", description):
        rows.append({"timing": "SWITCH_IN", "tag": "HEAL_ENERGY", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"入场前己方精灵每放1次" + _ELEMENT_WORD + r"系技能，?回复(\d+)能量", description):
        rows.append({"timing": "SWITCH_IN", "tag": "ENTRY_ENERGY_FROM_ELEMENT_COUNT", "params": {"element": match.group(1), "amount": int(match.group(2))}})
    if match := re.search(r"入场前己方精灵每成功应对1次，?回复(\d+)能量", description):
        rows.append({"timing": "SWITCH_IN", "tag": "ENTRY_ENERGY_FROM_COUNTER_COUNT", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"己方精灵每使用1次" + _ELEMENT_WORD + r"系技能，?自己入场时获得全技能能耗-(\d+)", description):
        rows.append({"timing": "SWITCH_IN", "tag": "ENTRY_BUFF_PER_SKILL_COUNT", "params": {"element": match.group(1), "mode": "cost", "amount": int(match.group(2))}})
    if match := re.search(r"己方精灵每使用1次" + _ELEMENT_WORD + r"系技能，?自己入场时获得全技能威力\+(\d+)", description):
        rows.append({"timing": "SWITCH_IN", "tag": "ENTRY_BUFF_PER_SKILL_COUNT", "params": {"element": match.group(1), "mode": "power", "amount": int(match.group(2))}})
    if "根据自己的血脉" in description or "根据自己的血脉，入场时" in description:
        rows.append({"timing": "SWITCH_IN", "tag": "BLOODLINE_ENTRY", "params": {"element": "萌"}})
    if match := re.search(r"入场时，?若敌方本回合换宠，?全属性提升(\d+)%", description):
        bonus = int(match.group(1)) / 100.0
        rows.append({
            "timing": "SWITCH_IN",
            "tag": "SELF_BUFF",
            "params": {"atk": bonus, "spatk": bonus, "def": bonus, "spdef": bonus, "speed": bonus},
        })


def _append_counter_and_combo_rules(rows: list[EffectRecord], description: str) -> None:
    if match := re.search(r"(防御|状态|攻击)技能应对(\d+)次后，?回满状态，?变为棋绮后", description):
        rows.append({
            "timing": "AFTER_MOVE",
            "tag": "COUNTER_ACCUMULATE_TRANSFORM",
            "params": {"category": match.group(1), "count": int(match.group(2)), "heal_full": True},
            "condition": "counter",
        })
    if "应对成功后，下次行动先手+1" in description:
        rows.append({"timing": "AFTER_MOVE", "tag": "COUNTER_SUCCESS_SPEED_PRIORITY", "params": {"priority": 1}, "condition": "counter"})
    if match := re.search(r"应对成功后，?下次行动技能能耗-(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "PASSIVE_ENERGY_REDUCE", "params": {"amount": int(match.group(1))}, "condition": "counter"})
    if "应对成功后，下次攻击威力翻倍" in description:
        rows.append({"timing": "BEFORE_MOVE", "tag": "POWER_DYNAMIC", "params": {"multiplier": 2.0}, "condition": "counter"})
    if match := re.search(r"应对成功后，?获得全技能威力永久\+(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "POWER_DYNAMIC", "params": {"bonus": int(match.group(1))}, "condition": "counter"})
    if match := re.search(r"防御技能应对成功时，?速度永久\+(\d+)", description):
        rows.append({"timing": "AFTER_MOVE", "tag": "SELF_BUFF", "params": {"speed": int(match.group(1)) / 100.0}, "condition": "counter"})
    if match := re.search(r"获得(\d+)次随机奉献", description):
        timing = "TURN_END" if "回合结束时" in description else "AFTER_MOVE"
        rows.append({"timing": timing, "tag": "DEVOTION_GRANT_RANDOM", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"若先于敌方行动，?行动后获得连击数\+(\d+)", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "FIRST_STRIKE_HIT_COUNT", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"使用翼系技能后，?获得连击数\+(\d+)", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "ON_SKILL_ELEMENT_HIT_COUNT", "params": {"element": "翼", "amount": int(match.group(1))}})
    if match := re.search(r"敌方每有1层中毒效果，?自己获得连击数\+(\d+)", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "HIT_COUNT_PER_POISON", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"自己每失去25%生命，?连击数\+(\d+)", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "STAT_SCALE_HITS_PER_HP_LOST", "params": {"amount": int(match.group(1))}})
    if match := re.search(r"自己每有1层萌化，?获得连击数\+(\d+)", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "CUTE_HIT_PER_STACK", "params": {"per": int(match.group(1))}})
    if match := re.search(r"造成克制伤害后，?获得攻防速\+(\d+)%.*回复(\d+)能量", description):
        bonus = int(match.group(1)) / 100.0
        rows.append({
            "timing": "AFTER_MOVE",
            "tag": "ON_SUPER_EFFECTIVE_BUFF",
            "params": {"buff": {"atk": bonus, "spatk": bonus, "def": bonus, "spdef": bonus, "speed": bonus}, "energy": int(match.group(2))},
        })
    if match := re.search(r"([1-4]号位(?:和[1-4]号位)?)技能获得(?:迅捷和)?传动(\d)(?:和威力\+(\d+))?", description):
        slots = _slots(match.group(1))
        drive = int(match.group(2))
        power = int(match.group(3) or 0)
        if "迅捷" in description:
            rows.append({"timing": "PASSIVE", "tag": "SKILL_MOD", "params": {"slots": slots, "priority": 1}})
        rows.append({"timing": "CALC_DAMAGE", "tag": "SKILL_MOD", "params": {"slots": slots, "drive": drive, "power_bonus": power}})


def _append_generic_rules(rows: list[EffectRecord], description: str) -> None:
    if match := re.search(r"(?:入场|回合开始).*获得(?:物攻|双攻)\+(\d+)%", description):
        bonus = int(match.group(1)) / 100.0
        rows.append({"timing": "BEFORE_MOVE", "tag": "SELF_BUFF", "params": {"atk": bonus, "spatk": bonus}})
    if match := re.search(r"速度\+(\d+)", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "SELF_BUFF", "params": {"speed": int(match.group(1)) / 100.0}})
    if match := re.search(r"伤害-(\d+)%", description):
        rows.append({"timing": "BEFORE_MOVE", "tag": "DAMAGE_REDUCTION", "params": {"pct": int(match.group(1)) / 100.0}})
    if "力竭" in description and not rows:
        rows.append({"timing": "PASSIVE", "tag": "FAINT_NO_MP_LOSS", "params": {}})
    if match := re.search(r"威力\+(\d+)%", description):
        rows.append({"timing": "CALC_DAMAGE", "tag": "POWER_DYNAMIC", "params": {"multiplier": 1 + int(match.group(1)) / 100.0}})
    if not rows and description.strip():
        buff = _generic_ability_buff(description)
        if buff:
            rows.append({"timing": "BEFORE_MOVE", "tag": "SELF_BUFF", "params": buff})


def _generic_ability_buff(description: str) -> dict[str, float]:
    buff = {"atk": 0.0, "spatk": 0.0, "def": 0.0, "spdef": 0.0, "speed": 0.0}
    stat_map = {
        "物攻": ("atk",),
        "魔攻": ("spatk",),
        "双攻": ("atk", "spatk"),
        "物防": ("def",),
        "魔防": ("spdef",),
        "双防": ("def", "spdef"),
        "攻防": ("atk", "spatk", "def", "spdef"),
    }
    for label, keys in stat_map.items():
        if match := re.search(label + r"\+(\d+)%", description):
            value = int(match.group(1)) / 100.0
            for key in keys:
                buff[key] += value
    return {key: value for key, value in buff.items() if value}


def _slots(text: str) -> list[int]:
    return [int(raw) - 1 for raw in re.findall(r"([1-4])号位", text)]


def _element_words(text: str) -> list[str]:
    return re.findall(_ELEMENT_WORD + r"系", text)


_ELEMENT_WORD = r"(普通|草|火|水|光|地|冰|龙|电|毒|虫|武|翼|萌|幽|恶|机械|幻)"
