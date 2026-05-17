"""Devotion subsystem — team-wide stackable buffs in packed ints."""

from roco.engine.state import DevotionIdx, EffectFlag, _unpack_devotion

DEVOTION_TYPES = {
    "假寐": DevotionIdx.JIAMEI, "飞断": DevotionIdx.FEIDUAN,
    "虫茧": DevotionIdx.CHONGJIAN, "捆缚": DevotionIdx.KUNFU,
    "虫群过境": DevotionIdx.CHONGQUN,
}

def register_devotion_stage_hooks(bus):
    from roco.engine.events import GameEvent, EventCtx

    def on_before_move(ctx):
        pet = ctx.actor; sk = ctx.skill
        if not pet or not sk or not (sk.effect_flags & EffectFlag.DEVOTION): return
        devo = ctx.state.devotion_a if pet in ctx.state.team_a else ctx.state.devotion_b
        jiamei = _unpack_devotion(devo, DevotionIdx.JIAMEI)
        if jiamei > 0: ctx.energy_delta -= jiamei
        feiduan = _unpack_devotion(devo, DevotionIdx.FEIDUAN)
        if feiduan > 0: ctx.power_mod += feiduan * 0.10
        chongqun = _unpack_devotion(devo, DevotionIdx.CHONGQUN)
        if chongqun > 0: sk.hit_count += chongqun

    bus.on(GameEvent.BEFORE_MOVE, on_before_move, priority=35, source="devotion")
