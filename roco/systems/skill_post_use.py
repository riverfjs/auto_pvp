"""POST_USE skill handlers — status, stat change, force switch, weather."""
from roco.engine.state import EffectFlag, StatusFlag, StatusType, BattleEvent, SkillCategory, Stats, WeatherType
from roco.engine.events import GameEvent, EventCtx
from roco.engine.damage import clamp_stage

def register(bus):
    def h_burn(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.burn_stacks <= 0: return
        if not ctx.target.is_immune_to(StatusFlag.BURN):
            ctx.target.status_flags |= StatusFlag.BURN
            ctx.target.set_status_count(StatusType.BURN, ctx.target.get_status_count(StatusType.BURN) + sk.burn_stacks)
    def h_poison(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.poison_stacks <= 0: return
        if not ctx.target.is_immune_to(StatusFlag.POISON):
            ctx.target.status_flags |= StatusFlag.POISON
            ctx.target.set_status_count(StatusType.POISON, ctx.target.get_status_count(StatusType.POISON) + sk.poison_stacks)
    def h_freeze(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.freeze_stacks <= 0: return
        if not ctx.target.is_immune_to(StatusFlag.FREEZE):
            ctx.target.status_flags |= StatusFlag.FREEZE
            ctx.target.set_status_count(StatusType.FREEZE, ctx.target.get_status_count(StatusType.FREEZE) + sk.freeze_stacks)
    def h_leech(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.leech_stacks <= 0: return
        ctx.target.status_flags |= StatusFlag.LEECH
        ctx.target.set_status_count(StatusType.LEECH, ctx.target.get_status_count(StatusType.LEECH) + sk.leech_stacks)
        ctx.target.leech_source = ctx.actor.persistent.name
    def h_stat_change(ctx):
        sk = ctx.data.get("skill")
        if not sk or not (sk.effect_flags & EffectFlag.STAT_CHANGE): return
        for idx, fn in [(0,"self_atk"),(3,"self_spatk"),(1,"self_def"),(4,"self_spdef")]:
            val = getattr(sk, fn, 0)
            if val != 0: ctx.actor.set_buff(idx, clamp_stage(ctx.actor.get_buff(idx) + round(val/0.10)))
        if sk.self_speed: ctx.actor.set_buff(2, clamp_stage(ctx.actor.get_buff(2) + round(sk.self_speed/0.10)))
        for idx, fn in [(0,"enemy_atk"),(3,"enemy_spatk"),(1,"enemy_def"),(4,"enemy_spdef")]:
            val = getattr(sk, fn, 0)
            if val != 0: ctx.target.set_buff(idx, clamp_stage(ctx.target.get_buff(idx) - round(abs(val)/0.10)))
        if sk.enemy_speed: ctx.target.set_buff(2, clamp_stage(ctx.target.get_buff(2) - round(abs(sk.enemy_speed)/0.10)))
    def h_force_switch(ctx):
        sk = ctx.data.get("skill")
        if not sk or not sk.force_switch: return
        s = ctx.state; team = s.team_a if ctx.actor in s.team_a else s.team_b
        alive = [i for i, p in enumerate(team) if not p.is_fainted and p != ctx.actor]
        if not alive: return
        if ctx.actor in s.team_a: s.active_a = alive[0]
        else: s.active_b = alive[0]
    def h_weather(ctx):
        sk = ctx.data.get("skill")
        if not sk or not sk.weather_type: return
        wm = {"sandstorm": WeatherType.SANDSTORM, "rain": WeatherType.RAIN, "snow": WeatherType.SNOW}
        wt = wm.get(sk.weather_type)
        if wt: ctx.state.weather_type = wt; ctx.state.weather_turns = 5
    def h_enemy_cost_up(ctx):
        sk = ctx.data.get("skill")
        if not sk or sk.enemy_cost_up_amount <= 0: return
        ctx.target._cost_mod += sk.enemy_cost_up_amount; ctx.target._cost_mod_turns = 3
    def h_permanent_mod(ctx):
        sk = ctx.data.get("skill")
        if not sk: return
        if sk.permanent_hit_growth: sk.hit_count += sk.permanent_hit_growth
        if sk.permanent_power_growth: sk.power += sk.permanent_power_growth

    bus.on(GameEvent.POST_USE, h_burn, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_poison, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_freeze, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_leech, priority=40, source="skill")
    bus.on(GameEvent.POST_USE, h_stat_change, priority=45, source="skill")
    bus.on(GameEvent.POST_USE, h_force_switch, priority=50, source="skill")
    bus.on(GameEvent.POST_USE, h_weather, priority=55, source="skill")
    bus.on(GameEvent.POST_USE, h_enemy_cost_up, priority=50, source="skill")
    bus.on(GameEvent.POST_USE, h_permanent_mod, priority=60, source="skill")
