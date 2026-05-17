"""Leech tick stage hook."""
from roco.engine.state import StatusFlag, StatusType, BattleEvent
from roco.engine.events import GameEvent, EventCtx

def register(bus):
    def h(ctx):
        for pet in (ctx.state.team_a[ctx.state.active_a], ctx.state.team_b[ctx.state.active_b]):
            if pet.is_fainted or not pet.leech_source: continue
            stacks = pet.get_status_count(StatusType.LEECH)
            if stacks <= 0: continue
            dmg = int(pet.max_hp * 0.08 * stacks)
            pet.current_hp = max(0, pet.current_hp - dmg)
            for team in (ctx.state.team_a, ctx.state.team_b):
                for p in team:
                    if p.persistent.name == pet.leech_source and not p.is_fainted:
                        p.current_hp = min(p.max_hp, p.current_hp + dmg)
                        break
    bus.on(GameEvent.TURN_END, h, priority=180, source="skill")
