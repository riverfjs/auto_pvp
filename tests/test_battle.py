"""Integration tests for the battle engine — new type system."""

import pytest
from roco.engine.battle import BattleEngine
from roco.engine.state import (
    BattleState, MoveDecision, PersistentPet, ActivePet as AP,
    SkillData, SkillCategory, StatusFlag, StatusType, Stats, WeatherType,
    _pack_buff, _unpack_buff,
)
from roco.engine.damage import calc_attack_damage
from roco.engine.effect_compile import compile_skill_effects
from roco.engine.skill_tags import classify

# ── Helpers ────────────────────────────────────────────────────

def _stat_dict(hp=100, atk=80, atk_m=80, df=80, df_m=80, spd=60):
    return {Stats.HP: hp, Stats.ATK_PHYS: atk, Stats.ATK_MAG: atk_m,
            Stats.DEF_PHYS: df, Stats.DEF_MAG: df_m, Stats.SPEED: spd}

def _mk_skill(name="撞击", element="普通", cat=SkillCategory.PHYSICAL,
              energy=1, power=50, effect=""):
    sk = SkillData(name=name, element=element, category=cat, energy=energy, power=power, effect=effect)
    classify(sk)
    sk.effects = compile_skill_effects(0, sk)
    return sk

def _mk_pet(name="A", hp=100, atk=80, spd=60, element="普通", moves=None, nature="", ivs=None):
    pp = PersistentPet(
        name=name, stats=_stat_dict(hp=hp, atk=atk, spd=spd),
        types=(element, ""), moves=moves or [_mk_skill()],
        nature=nature, ivs=ivs or [])
    return pp

def _act(persistent): return AP(persistent)

_tackle = lambda: _mk_skill("撞击", "普通", SkillCategory.PHYSICAL, 1, 50)
_ember = lambda: _mk_skill("火花", "火", SkillCategory.MAGICAL, 2, 60)
_water_gun = lambda: _mk_skill("水枪", "水", SkillCategory.MAGICAL, 2, 60)
_wisp = lambda: _mk_skill("鬼火", "火", SkillCategory.STATUS, 2, 0, "造成3层灼烧")
_def_curl = lambda: _mk_skill("防御", "普通", SkillCategory.DEFENSE, 1, 0, "减伤70%")

def _move(idx): return MoveDecision(action="move", skill_index=idx)
def _switch(idx): return MoveDecision(action="switch", switch_slot=idx)


# ── Basic flow ─────────────────────────────────────────────────

def test_single_turn_attack():
    engine = BattleEngine(
        [_mk_pet("火龙", hp=120, atk=100, spd=80, element="火", moves=[_ember(), _tackle()]),
         _mk_pet("草龟", hp=150, atk=70, spd=40, element="草", moves=[_water_gun(), _tackle()])],
        [_mk_pet("水蛇", hp=100, atk=90, spd=70, element="水", moves=[_water_gun(), _tackle()]),
         _mk_pet("雷鸟", hp=80, atk=110, spd=110, element="电", moves=[_ember(), _tackle()])])
    engine.step(_move(0), _move(0))
    assert engine.state.turn_number == 1
    assert engine.state.team_a[0].current_hp < engine.state.team_a[0].max_hp

def test_energy_consumed():
    engine = BattleEngine(
        [_mk_pet("A", hp=999, atk=50, element="火", moves=[_ember()])],
        [_mk_pet("B", hp=999, atk=50, element="火", moves=[_ember()])])
    engine.step(_move(0), _move(0))
    assert engine.get_active("a").current_energy == 8

def test_faint_and_auto_switch():
    engine = BattleEngine(
        [_mk_pet("K", hp=200, atk=150, spd=200, element="火", moves=[_ember()])],
        [_mk_pet("S1", hp=10, atk=50, spd=10, element="草", moves=[_tackle()]),
         _mk_pet("S2", hp=100, atk=80, spd=80, element="水", moves=[_water_gun()])])
    engine.step(_move(0), _move(0))
    assert engine.state.team_b[0].is_fainted
    assert engine.state.active_b == 1

def test_win_condition():
    engine = BattleEngine(
        [_mk_pet("K", hp=200, atk=500, spd=200, element="火", moves=[_ember()])],
        [_mk_pet("S", hp=10, atk=50, spd=10, element="草", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    assert engine.is_finished()
    assert engine.get_winner() == "a"

def test_faster_moves_first():
    engine = BattleEngine(
        [_mk_pet("Fast", hp=100, atk=100, spd=200, element="普通", moves=[_ember()])],
        [_mk_pet("Slow", hp=10, atk=50, spd=1, element="草", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    assert engine.state.team_b[0].is_fainted
    assert engine.state.team_a[0].current_hp == engine.state.team_a[0].max_hp

def test_burn_application():
    engine = BattleEngine(
        [_mk_pet("火使", hp=100, atk=80, spd=100, element="火", moves=[_wisp()])],
        [_mk_pet("靶子", hp=100, atk=80, spd=50, element="草", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    assert engine.state.team_b[0].has_status(StatusFlag.BURN)

def test_fire_immune_to_burn():
    engine = BattleEngine(
        [_mk_pet("火使", hp=100, atk=80, spd=100, element="火", moves=[_wisp()])],
        [_mk_pet("火靶", hp=100, atk=80, spd=50, element="火", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    assert not engine.state.team_b[0].has_status(StatusFlag.BURN)

def test_super_effective():
    engine = BattleEngine(
        [_mk_pet("A", hp=100, atk=100, spd=100, element="火", moves=[_ember()])],
        [_mk_pet("B", hp=100, atk=80, spd=50, element="草", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    atks = [e for e in engine.state.log if e.action == "attack"]
    assert atks[0].detail["type_mult"] == 2.0

def test_resisted():
    engine = BattleEngine(
        [_mk_pet("A", hp=100, atk=100, spd=100, element="火", moves=[_ember()])],
        [_mk_pet("B", hp=100, atk=80, spd=50, element="水", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    atks = [e for e in engine.state.log if e.action == "attack"]
    assert atks[0].detail["type_mult"] == 0.5

def test_deterministic():
    def run():
        engine = BattleEngine(
            [_mk_pet("A", hp=120, atk=100, spd=80, element="火", moves=[_ember(), _tackle()]),
             _mk_pet("B", hp=150, atk=70, spd=40, element="草", moves=[_water_gun(), _tackle()])],
            [_mk_pet("C", hp=100, atk=90, spd=70, element="水", moves=[_water_gun(), _tackle()]),
             _mk_pet("D", hp=80, atk=110, spd=110, element="电", moves=[_ember(), _tackle()])])
        engine.step(_move(0), _move(0))
        engine.step(_move(1), _move(1))
        return (engine.state.team_a[0].current_hp, engine.state.team_b[0].current_hp)
    assert run() == run()

def test_defense_curl():
    engine = BattleEngine(
        [_mk_pet("盾", hp=999, atk=50, spd=200, element="普通", moves=[_def_curl()])],
        [_mk_pet("靶", hp=100, atk=50, spd=50, element="普通", moves=[_tackle()])])
    engine.step(_move(0), _move(0))
    buffs = [e for e in engine.state.log if e.action == "buff" and "defense" in str(e.detail)]
    assert len(buffs) >= 1

def test_full_6v6():
    team_a = [_mk_pet(f"A{i}", hp=100, atk=80, spd=100-i*10, element="普通",
                      moves=[_tackle(), _ember()]) for i in range(6)]
    team_b = [_mk_pet(f"B{i}", hp=100, atk=80, spd=100-i*10, element="普通",
                      moves=[_tackle(), _ember()]) for i in range(6)]
    engine = BattleEngine(team_a, team_b)
    for _ in range(200):
        if engine.is_finished(): break
        am = engine.get_valid_moves("a"); bm = engine.get_valid_moves("b")
        engine.step(_move(am[0] if am else 0), _move(bm[0] if bm else 0))
    assert engine.get_winner() in ("a", "b", "draw")

def test_magic_power():
    engine = BattleEngine(
        [_mk_pet("K", hp=200, atk=500, spd=200, element="火", moves=[_ember()])],
        [_mk_pet(f"S{i}", hp=10, atk=50, spd=10, element="草", moves=[_tackle()]) for i in range(6)])
    assert engine.state.magic_b == 4
    engine.step(_move(0), _move(0))
    assert engine.state.magic_b == 3

def test_fake_death_no_magic_cost():
    engine = BattleEngine(
        [_mk_pet("K", hp=200, atk=500, spd=200, element="火", moves=[_ember()])],
        [_mk_pet("卡瓦重", hp=50, atk=50, spd=10, element="地", moves=[_tackle()])])
    engine.state.team_b[0].persistent.add_ability_tag("fake_death")
    assert engine.state.magic_b == 4
    engine.step(_move(0), _move(0))
    assert engine.state.magic_b == 4

def test_magic_power_display():
    engine = BattleEngine(
        [_mk_pet("A", hp=100, atk=50, spd=50, moves=[_tackle()])],
        [_mk_pet("B", hp=100, atk=50, spd=50, moves=[_tackle()])])
    assert engine.state.magic_a == 4
    assert engine.state.magic_b == 4
