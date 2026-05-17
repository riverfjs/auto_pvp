"""Dispatch compiled skill and ability effect rows."""

from __future__ import annotations

from roco.engine.effect_model import EffectTag, Timing
from roco.engine.effects import OP_TABLE
from roco.engine.events import EventCtx
from roco.engine.state import ActivePet


def run_skill_effects(ctx: EventCtx, timing: Timing) -> None:
    skill = ctx.skill
    if not skill:
        return
    for item in skill.effects:
        if item.effect.timing is timing:
            execute_effect_op(ctx, item.effect.tag, item.effect.params, source=f"skill:{skill.name}")


def run_ability_effects(ctx: EventCtx, pet: ActivePet, timing: Timing) -> None:
    for item in pet.persistent.ability_effects:
        if item.effect.timing is timing:
            if not _matches_filter(ctx, item.effect.params):
                continue
            execute_effect_op(
                ctx,
                item.effect.tag,
                item.effect.params,
                source=f"ability:{pet.persistent.ability_name}",
                owner=pet,
            )


def execute_effect_op(
    ctx: EventCtx,
    tag: EffectTag,
    params,
    source: str,
    owner: ActivePet | None = None,
) -> None:
    actor = owner or ctx.actor
    if actor is None:
        return
    op = OP_TABLE[tag.value] if tag.value < len(OP_TABLE) else None
    if op is None:
        if tag is EffectTag.UNSUPPORTED:
            raise NotImplementedError(f"unsupported runtime effect: {dict(params)} from {source}")
        raise NotImplementedError(f"unhandled runtime effect: {tag.name} from {source}")
    op(ctx, actor, params, source)


def _matches_filter(ctx: EventCtx, params) -> bool:
    filt = params.get("_filter", {})
    if not filt:
        return True
    skill = ctx.skill
    if skill is None:
        return not any(k in filt for k in ("element", "category"))
    element = filt.get("element")
    if element:
        allowed = element if isinstance(element, (list, tuple, set)) else (element,)
        if skill.element not in allowed:
            return False
    category = filt.get("category")
    if category and str(category) != skill.category.name:
        return False
    return True
