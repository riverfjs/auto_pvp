"""Data-shaped ability system — per-Pet handler registration on EventBus."""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from roco.engine.events import EventBus, EventCtx
    from roco.engine.state import ActivePet
from roco.engine.state import AbilityFlag, Timing

AbilityFn = Callable[["EventCtx", "ActivePet"], None]


@dataclass(frozen=True, slots=True)
class AbilityRule:
    timing: Timing
    event_name: str
    handler: AbilityFn
    tag: str = ""

def _intimidate(ctx, pet): 
    s = ctx.state; opp_team = s.team_b if pet in s.team_a else s.team_a
    opp = opp_team[s.active_b if pet in s.team_a else s.active_a]
    opp.set_buff(0, max(-6, opp.get_buff(0) - 2))
    opp.set_buff(3, max(-6, opp.get_buff(3) - 2))

def _iron_fist(ctx, pet): pet.power_mult = int(pet.power_mult * 1.2)
def _energy_eater(ctx, pet): pet.current_energy = min(10, pet.current_energy + 2)
def _photosynthesis(ctx, pet): pet.current_hp = min(pet.max_hp, pet.current_hp + int(pet.max_hp * 0.05))

def _auto_switch(ctx, pet):
    if pet.current_energy > 0: return
    s = ctx.state; team = s.team_a if pet in s.team_a else s.team_b
    alive = [i for i, p in enumerate(team) if not p.is_fainted and p != pet]
    if not alive: return
    if pet in s.team_a: s.active_a = alive[0]
    else: s.active_b = alive[0]

def _fake_death(ctx, pet):
    pet.set_ability_flag(AbilityFlag.FAKE_DEATH)


def _revive_tag(ctx, pet):
    pet.set_ability_flag(AbilityFlag.REVIVE)


ABILITY_RULES: dict[str, tuple[AbilityRule, ...]] = {
    "诈死": (AbilityRule(Timing.PASSIVE, "PASSIVE", _fake_death, "fake_death"),),
    "威慑": (AbilityRule(Timing.SWITCH_IN, "SWITCH_IN", _intimidate),),
    "铁拳": (AbilityRule(Timing.SWITCH_IN, "SWITCH_IN", _iron_fist),),
    "加速": (AbilityRule(Timing.SWITCH_IN, "SWITCH_IN", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.1))),),
    "好胜": (AbilityRule(Timing.SWITCH_IN, "SWITCH_IN", lambda c,p: (p.set_buff(0,1), p.set_buff(3,1))),),
    "贪吃": (AbilityRule(Timing.SWITCH_IN, "SWITCH_IN", lambda c,p: setattr(p,'current_energy',min(10,p.current_energy+2))),),
    "传递": (AbilityRule(Timing.SWITCH_OUT, "SWITCH_OUT", lambda c,p: setattr(c.target,'power_mult',int(getattr(c.target,'power_mult',100)*1.05)) if c.target else None),),
    "食能": (AbilityRule(Timing.KILL, "KILL", _energy_eater),),
    "杀意": (AbilityRule(Timing.KILL, "KILL", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.05))),),
    "光合": (AbilityRule(Timing.ON_DAMAGE, "TAKE_DAMAGE", _photosynthesis),),
    "铁壁": (AbilityRule(Timing.ON_DAMAGE, "TAKE_DAMAGE", lambda c,p: p.set_buff(1, max(-6, p.get_buff(1)+1))),),
    "连打": (AbilityRule(Timing.COUNTER_SUCCESS, "COUNTER_SUCCESS", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.3))),),
    "协防": (AbilityRule(Timing.COUNTER_SUCCESS, "ALLY_COUNTER", lambda c,p: p.set_buff(1, max(-6, p.get_buff(1)+1))),),
    "先发": (AbilityRule(Timing.BATTLE_START, "BATTLE_START", lambda c,p: setattr(p,'current_energy',min(10,p.current_energy+2))),),
    "追击": (AbilityRule(Timing.SWITCH_IN, "ENEMY_SWITCH", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.2))),),
    "蓄能": (AbilityRule(Timing.TURN_END, "TURN_END", lambda c,p: setattr(p,'current_energy',min(10,p.current_energy+1))),),
    "疾风": (AbilityRule(Timing.TURN_START, "TURN_START", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.15)) if p.current_hp==p.max_hp else 1.0),),
    "不朽": (AbilityRule(Timing.FAINT, "BE_KILLED", _revive_tag),),
    "守卫": (AbilityRule(Timing.PASSIVE, "PASSIVE", lambda c,p: (p.set_buff(1,1), p.set_buff(4,1))),),
    "奋勇": (AbilityRule(Timing.PASSIVE, "PASSIVE", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.1))),),
    "防过载": (AbilityRule(Timing.TURN_START, "TURN_START", _auto_switch),),
}

ABILITY_TAG_MAP = {n: n for n in ABILITY_RULES}

def register_ability_handlers(bus, pet):
    from roco.engine.events import GameEvent
    name = pet.persistent.ability_name
    if not name or name not in ABILITY_RULES: return
    tag = ABILITY_TAG_MAP.get(name, "")
    if tag and tag not in pet.persistent.ability_tags:
        pet.persistent.ability_tags.append(tag)
    event_map = {e.name: e for e in GameEvent}
    for rule in ABILITY_RULES[name]:
        evt = event_map.get(rule.event_name)
        if evt:
            def handler(ctx, pet=pet, fn=rule.handler, event_name=rule.event_name):
                if event_name not in {"BATTLE_START", "TURN_START", "TURN_END"} and ctx.actor is not pet:
                    return
                fn(ctx, pet)
            bus.on(evt, handler, priority=100, source=f"ability:{name}")
