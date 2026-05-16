"""POST_USE skill handlers — status, stat change, force switch, weather, perma mods."""
from roco.engine.events import GameEvent, EventCtx
from roco.engine.damage import clamp_stage


def register(bus: "EventBus") -> None:
    def h_burn(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.burn_stacks <= 0:
            return
        if not ctx.target.is_immune_to_status("灼烧"):
            ctx.target.status_stacks["灼烧"] = ctx.target.status_stacks.get("灼烧", 0) + skill.burn_stacks

    def h_poison(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.poison_stacks <= 0:
            return
        if not ctx.target.is_immune_to_status("中毒"):
            ctx.target.status_stacks["中毒"] = ctx.target.status_stacks.get("中毒", 0) + skill.poison_stacks

    def h_freeze(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.freeze_stacks <= 0:
            return
        if not ctx.target.is_immune_to_status("冻结"):
            ctx.target.status_stacks["冻结"] = ctx.target.status_stacks.get("冻结", 0) + skill.freeze_stacks

    def h_leech(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.leech_stacks <= 0:
            return
        ctx.target.status_stacks["寄生"] = ctx.target.status_stacks.get("寄生", 0) + skill.leech_stacks
        ctx.target.leech_source = ctx.actor.name

    def h_stat_change(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or "stat_change" not in skill.tags:
            return
        for stat_key, field_name in [
            ("atk_phys", "self_atk"), ("atk_mag", "self_spatk"),
            ("def_phys", "self_def"), ("def_mag", "self_spdef"),
        ]:
            val = getattr(skill, field_name, 0)
            if val != 0:
                ctx.actor.buff_stages[stat_key] = clamp_stage(
                    ctx.actor.buff_stages.get(stat_key, 0) + round(val / 0.10))
        spd = skill.self_speed
        if spd != 0:
            ctx.actor.buff_stages["speed"] = clamp_stage(
                ctx.actor.buff_stages.get("speed", 0) + round(spd / 0.10))
        for stat_key, field_name in [
            ("atk_phys", "enemy_atk"), ("atk_mag", "enemy_spatk"),
            ("def_phys", "enemy_def"), ("def_mag", "enemy_spdef"),
        ]:
            val = getattr(skill, field_name, 0)
            if val != 0:
                ctx.target.buff_stages[stat_key] = clamp_stage(
                    ctx.target.buff_stages.get(stat_key, 0) - round(abs(val) / 0.10))
        if skill.enemy_speed != 0:
            ctx.target.buff_stages["speed"] = clamp_stage(
                ctx.target.buff_stages.get("speed", 0) - round(abs(skill.enemy_speed) / 0.10))

    def h_force_switch(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not skill.force_switch:
            return
        state = ctx.state
        team = state.team_a if ctx.actor in state.team_a else state.team_b
        alive = [i for i, p in enumerate(team) if not p.is_fainted and p != ctx.actor]
        if not alive:
            return
        new_idx = alive[0]
        if ctx.actor in state.team_a:
            state.active_a = new_idx
        else:
            state.active_b = new_idx

    def h_weather(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or not skill.weather_type:
            return
        ctx.state.weather, ctx.state.weather_turns = skill.weather_type, 5

    def h_enemy_cost_up(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill or skill.enemy_cost_up_amount <= 0:
            return
        ctx.target._cost_mod = getattr(ctx.target, "_cost_mod", 0) + skill.enemy_cost_up_amount
        ctx.target._cost_mod_turns = 3

    def h_permanent_mod(ctx: EventCtx) -> None:
        skill = ctx.data.get("skill")
        if not skill:
            return
        if skill.permanent_hit_growth:
            skill.hit_count += skill.permanent_hit_growth
        if skill.permanent_power_growth:
            skill.power += skill.permanent_power_growth

    bus.on(GameEvent.POST_USE, h_burn, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_poison, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_freeze, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_leech, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_stat_change, priority=45, source="skill")
    bus.on(GameEvent.POST_USE, h_force_switch, priority=50, source="skill")
    bus.on(GameEvent.POST_USE, h_weather, priority=55, source="skill")
    bus.on(GameEvent.POST_USE, h_enemy_cost_up, priority=50, source="skill")
    bus.on(GameEvent.POST_USE, h_permanent_mod, priority=60, source="skill")
