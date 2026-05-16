"""Leech tick handler — end-of-turn leech damage + heal caster."""
from roco.engine.events import GameEvent, EventCtx
from roco.engine.state import BattleEvent


def register(bus: "EventBus") -> None:
    def h_leech_tick(ctx: EventCtx) -> None:
        state = ctx.state
        for pet in state.team_a + state.team_b:
            stacks = pet.status_stacks.get("寄生", 0)
            if stacks <= 0 or pet.is_fainted or not pet.leech_source:
                continue
            dmg = int(pet.max_hp * 0.08 * stacks)
            pet.current_hp = max(0, pet.current_hp - dmg)
            for team in (state.team_a, state.team_b):
                for p in team:
                    if p.name == pet.leech_source and not p.is_fainted:
                        p.current_hp = min(p.max_hp, p.current_hp + dmg)
                        break
            state.log.append(BattleEvent(
                turn=state.turn_number, actor=pet.name, action="status_tick",
                detail={"status": "寄生", "damage": dmg, "stacks": stacks}))

    bus.on(GameEvent.TURN_END, h_leech_tick, priority=180, source="skill")
