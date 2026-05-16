"""Ability system — per-pet handler registration on EventBus."""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable
if TYPE_CHECKING:
    from roco.engine.events import EventBus, EventCtx
    from roco.engine.state import ActivePokemon

AbilityFn = Callable[["EventCtx", "ActivePokemon"], None]

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

ABILITY_DB = {
    "诈死": [("FAINT", lambda c,p: None)],
    "威慑": [("SWITCH_IN", _intimidate)],
    "铁拳": [("SWITCH_IN", _iron_fist)],
    "加速": [("SWITCH_IN", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.1)))],
    "好胜": [("SWITCH_IN", lambda c,p: (p.set_buff(0,1), p.set_buff(3,1)))],
    "贪吃": [("SWITCH_IN", lambda c,p: setattr(p,'current_energy',min(10,p.current_energy+2)))],
    "传递": [("SWITCH_OUT", lambda c,p: setattr(c.target,'power_mult',int(getattr(c.target,'power_mult',100)*1.05)) if c.target else None)],
    "食能": [("KILL", _energy_eater)],
    "杀意": [("KILL", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.05)))],
    "光合": [("TAKE_DAMAGE", _photosynthesis)],
    "铁壁": [("TAKE_DAMAGE", lambda c,p: p.set_buff(1, max(-6, p.get_buff(1)+1)))],
    "连打": [("COUNTER_SUCCESS", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.3)))],
    "协防": [("ALLY_COUNTER", lambda c,p: p.set_buff(1, max(-6, p.get_buff(1)+1)))],
    "先发": [("BATTLE_START", lambda c,p: setattr(p,'current_energy',min(10,p.current_energy+2)))],
    "追击": [("ENEMY_SWITCH", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.2)))],
    "蓄能": [("TURN_END", lambda c,p: setattr(p,'current_energy',min(10,p.current_energy+1)))],
    "疾风": [("TURN_START", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.15)) if p.current_hp==p.max_hp else 1.0)],
    "不朽": [("BE_KILLED", lambda c,p: p.persistent.ability_tags.append("revive"))],
    "守卫": [("PASSIVE", lambda c,p: (p.set_buff(1,1), p.set_buff(4,1)))],
    "奋勇": [("PASSIVE", lambda c,p: setattr(p,'power_mult',int(p.power_mult*1.1)))],
    "防过载": [("TURN_START", _auto_switch)],
}

ABILITY_TAG_MAP = {n: n for n in ABILITY_DB}

def register_ability_handlers(bus, pet):
    from roco.engine.events import GameEvent
    name = pet.persistent.ability_name
    if not name or name not in ABILITY_DB: return
    pet.persistent.ability_tags.append(ABILITY_TAG_MAP.get(name, ""))
    event_map = {e.name: e for e in GameEvent}
    for evt_name, fn in ABILITY_DB[name]:
        evt = event_map.get(evt_name)
        if evt:
            def handler(ctx, pet=pet, fn=fn): fn(ctx, pet)
            bus.on(evt, handler, priority=100, source=f"ability:{name}")
