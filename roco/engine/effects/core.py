"""Core skill and status effect handlers."""

from __future__ import annotations

from roco.config.constants import MAX_ENERGY
from roco.engine.effect_model import EffectTag
from roco.engine.enums import StatusFlag, StatusType
from roco.engine.events import EventCtx
from roco.engine.state import ActivePet

from .common import (
    EffectHandler,
    EffectParams,
    add_meteor_mark,
    add_status,
    apply_buff,
    apply_permanent_skill_mod,
    dispel_positive_buffs,
    force_switch,
    heal_hp,
    log_effect,
    set_weather,
)


def h_damage(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    return


def h_damage_reduction(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor._defense_reduction = max(actor._defense_reduction, float(params.get("pct", 0)))
    log_effect(ctx, actor, "buff", {"source": source, "defense": f"{actor._defense_reduction:.0%}"})


def h_energy_all_in(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    spent = actor.current_energy
    if spent > 0:
        ctx.power_mod += spent * float(params.get("power_per_energy", 0.25))
        ctx.cost = spent


def h_heal_hp(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    heal_hp(actor, int(actor.max_hp * float(params.get("pct", params.get("heal_pct", 0)))))


def h_heal_energy(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.current_energy = min(MAX_ENERGY, actor.current_energy + int(params.get("amount", 0)))


def h_steal_energy(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    target = ctx.target
    if target is None:
        return
    amount = min(int(params.get("amount", 0)), target.current_energy)
    target.current_energy -= amount
    actor.current_energy = min(MAX_ENERGY, actor.current_energy + amount)


def h_enemy_lose_energy(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        ctx.target.current_energy = max(0, ctx.target.current_energy - int(params.get("amount", 0)))


def h_life_drain(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    heal_hp(actor, int(ctx.damage * float(params.get("pct", 0))))


def h_self_buff(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    apply_buff(actor, params, sign=1)


def h_self_debuff(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    apply_buff(actor, params, sign=-1)


def h_enemy_debuff(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        apply_buff(ctx.target, params, sign=-1)


def h_dispel_buffs(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    target = ctx.target if params.get("target", "enemy") == "enemy" else actor
    if target is not None:
        dispel_positive_buffs(target)


def h_burn(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        add_status(ctx.target, StatusType.BURN, StatusFlag.BURN, int(params.get("stacks", 1)))


def h_poison(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        add_status(ctx.target, StatusType.POISON, StatusFlag.POISON, int(params.get("stacks", 1)))


def h_freeze(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        stacks = int(params.get("stacks", 1)) + actor.extra_freeze_stacks
        add_status(ctx.target, StatusType.FREEZE, StatusFlag.FREEZE, stacks)


def h_leech(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is None:
        return
    add_status(ctx.target, StatusType.LEECH, StatusFlag.LEECH, int(params.get("stacks", 1)), immune=False)
    ctx.target.leech_source = actor.persistent.name


def h_meteor(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    add_meteor_mark(ctx, ctx.target, int(params.get("stacks", 1)))


def h_force_switch(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    force_switch(ctx, actor)


def h_weather(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    set_weather(ctx, str(params.get("type", "")), int(params.get("turns", 5)))


def h_enemy_energy_cost_up(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        ctx.target._cost_mod += int(params.get("amount", 0))
        ctx.target._cost_mod_turns = int(params.get("turns", 3))


def h_hp_for_energy(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.current_hp = max(0, actor.current_hp - int(actor.max_hp * float(params.get("pct", 0.05))))


def h_permanent_mod(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    apply_permanent_skill_mod(ctx, params)


def h_skill_mod(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    stat = str(params.get("stat", ""))
    value = params.get("value", 0)
    if stat == "power_pct":
        ctx.power_mod += float(value)
    elif stat == "power":
        ctx.power_bonus += int(value)
    elif stat == "hit_count":
        ctx.hit_count_delta += int(value)
    elif stat == "hit_count_mult":
        ctx.hit_count_mult *= float(value)
    elif stat == "cost":
        target = ctx.target if params.get("target") == "enemy" else actor
        if target is not None:
            target._cost_mod += int(value)


def h_next_attack_mod(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.next_power_bonus += int(params.get("power_bonus", 0))
    actor.next_power_pct_bps += int(float(params.get("power_pct", 0.0)) * 10000)


def h_power_dynamic(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    condition = params.get("condition")
    if condition == "first_strike" and not ctx.first_strike:
        return
    if "multiplier" in params:
        ctx.power_mod *= float(params["multiplier"])
    if "bonus_pct" in params:
        ctx.power_mod += float(params["bonus_pct"])
    if "power_bonus" in params:
        ctx.power_bonus += int(params["power_bonus"])


def h_agility(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    return


HANDLER_ROWS: tuple[tuple[EffectTag, EffectHandler], ...] = (
    (EffectTag.DAMAGE, h_damage),
    (EffectTag.DAMAGE_REDUCTION, h_damage_reduction),
    (EffectTag.ENERGY_ALL_IN, h_energy_all_in),
    (EffectTag.HEAL_HP, h_heal_hp),
    (EffectTag.HEAL_ENERGY, h_heal_energy),
    (EffectTag.STEAL_ENERGY, h_steal_energy),
    (EffectTag.ENEMY_LOSE_ENERGY, h_enemy_lose_energy),
    (EffectTag.LIFE_DRAIN, h_life_drain),
    (EffectTag.SELF_BUFF, h_self_buff),
    (EffectTag.SELF_DEBUFF, h_self_debuff),
    (EffectTag.ENEMY_DEBUFF, h_enemy_debuff),
    (EffectTag.DISPEL_BUFFS, h_dispel_buffs),
    (EffectTag.BURN, h_burn),
    (EffectTag.POISON, h_poison),
    (EffectTag.FREEZE, h_freeze),
    (EffectTag.LEECH, h_leech),
    (EffectTag.METEOR, h_meteor),
    (EffectTag.FORCE_SWITCH, h_force_switch),
    (EffectTag.WEATHER, h_weather),
    (EffectTag.ENEMY_ENERGY_COST_UP, h_enemy_energy_cost_up),
    (EffectTag.HP_FOR_ENERGY, h_hp_for_energy),
    (EffectTag.PERMANENT_MOD, h_permanent_mod),
    (EffectTag.SKILL_MOD, h_skill_mod),
    (EffectTag.NEXT_ATTACK_MOD, h_next_attack_mod),
    (EffectTag.POWER_DYNAMIC, h_power_dynamic),
    (EffectTag.AGILITY, h_agility),
)
