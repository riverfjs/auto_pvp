"""Ability and subsystem flag effect handlers."""

from __future__ import annotations

from roco.config.constants import MAX_ENERGY
from roco.engine.effect_model import EffectTag
from roco.engine.enums import AbilityFlag
from roco.engine.events import EventCtx
from roco.engine.state import ActivePet

from .common import EffectHandler, EffectParams, force_switch


def h_faint_no_mp_loss(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.set_ability_flag(AbilityFlag.FAKE_DEATH)
    actor.persistent.add_ability_tag("fake_death")


def h_energy_regen_per_turn(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.current_energy = min(MAX_ENERGY, actor.current_energy + int(params.get("amount", 1)))


def h_power_multiplier_buff(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.power_mult = int(actor.power_mult * float(params.get("multiplier", 1.0)))


def h_first_strike_power_bonus(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.first_strike:
        ctx.power_mod += float(params.get("bonus_pct", 0.0))


def h_auto_switch_on_zero_energy(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if actor.current_energy <= 0:
        force_switch(ctx, actor)


def h_auto_switch_after_action(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    force_switch(ctx, actor)


def h_leave_energy_refill(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.current_energy = min(MAX_ENERGY, actor.current_energy + int(params.get("amount", 10)))


def h_set_ability_flag(flag: AbilityFlag) -> EffectHandler:
    def handler(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
        actor.set_ability_flag(flag)

    return handler


def h_extra_freeze_on_freeze(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.extra_freeze_stacks = max(actor.extra_freeze_stacks, int(params.get("extra", 2)))


def h_burst_power_bonus(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.burst_power_bonus = int(params.get("bonus", actor.burst_power_bonus))


def h_burst_enemy_cost_up(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.burst_enemy_cost_up = int(params.get("amount", 1))


def h_burst_element_cost_reduce(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.burst_element_cost_reduce = str(params.get("element", ""))


def h_burst_extend(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.burst_extend = int(params.get("extend", 1))


def h_cute_gain(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    actor.cute += int(params.get("stacks", 1))


def h_cute_both(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    stacks = int(params.get("stacks", 1))
    actor.cute += stacks
    if ctx.target is not None:
        ctx.target.cute += stacks


def h_cute_enemy_gain(ctx: EventCtx, actor: ActivePet, params: EffectParams, source: str) -> None:
    if ctx.target is not None:
        ctx.target.cute += int(params.get("stacks", 1))


HANDLER_ROWS: tuple[tuple[EffectTag, EffectHandler], ...] = (
    (EffectTag.FAINT_NO_MP_LOSS, h_faint_no_mp_loss),
    (EffectTag.ENERGY_REGEN_PER_TURN, h_energy_regen_per_turn),
    (EffectTag.POWER_MULTIPLIER_BUFF, h_power_multiplier_buff),
    (EffectTag.FIRST_STRIKE_POWER_BONUS, h_first_strike_power_bonus),
    (EffectTag.AUTO_SWITCH_ON_ZERO_ENERGY, h_auto_switch_on_zero_energy),
    (EffectTag.AUTO_SWITCH_AFTER_ACTION, h_auto_switch_after_action),
    (EffectTag.LEAVE_ENERGY_REFILL, h_leave_energy_refill),
    (EffectTag.BARREL_STATE, h_set_ability_flag(AbilityFlag.BARREL_ACTIVE)),
    (EffectTag.ENERGY_NO_CAP, h_set_ability_flag(AbilityFlag.ENERGY_NO_CAP)),
    (EffectTag.BURN_NO_DECAY, h_set_ability_flag(AbilityFlag.BURN_NO_DECAY)),
    (EffectTag.EXTRA_POISON_TICK, h_set_ability_flag(AbilityFlag.EXTRA_POISON_TICK)),
    (EffectTag.EXTRA_FREEZE_ON_FREEZE, h_extra_freeze_on_freeze),
    (EffectTag.BURST_POWER_BONUS, h_burst_power_bonus),
    (EffectTag.BURST_ENEMY_COST_UP, h_burst_enemy_cost_up),
    (EffectTag.BURST_ELEMENT_COST_REDUCE, h_burst_element_cost_reduce),
    (EffectTag.BURST_EXTEND, h_burst_extend),
    (EffectTag.CUTE_GAIN, h_cute_gain),
    (EffectTag.CUTE_BOTH, h_cute_both),
    (EffectTag.CUTE_ENEMY_GAIN, h_cute_enemy_gain),
)
