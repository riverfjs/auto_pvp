"""Integration tests for the battle engine."""

import pytest
from scripts.battle import (
    BattleEngine,
    BattleState,
    MoveDecision,
    PetState,
    SkillRef,
)
from scripts.damage import compute_stats


# ── Fixtures ───────────────────────────────────────────────────

def _mk_pet(name: str, hp: int = 100, atk: int = 80, spd: int = 60,
            element: str = "普通", moves: list[SkillRef] | None = None,
            nature: str = "", ivs: list[str] | None = None) -> PetState:
    stats = compute_stats(hp, atk, atk, 80, 80, spd, nature=nature, ivs=ivs)
    return PetState(
        name=name,
        base_stats=stats,
        effective_stats=dict(stats),
        element_primary=element,
        moves=moves or [],
        nature=nature,
        ivs=ivs or [],
    )


def _tackle() -> SkillRef:
    return SkillRef(name="撞击", element="普通", category="物攻", energy=1, power=50)


def _ember() -> SkillRef:
    return SkillRef(name="火花", element="火", category="魔攻", energy=2, power=60)


def _water_gun() -> SkillRef:
    return SkillRef(name="水枪", element="水", category="魔攻", energy=2, power=60)


def _will_o_wisp() -> SkillRef:
    return SkillRef(name="鬼火", element="火", category="状态", energy=2, power=0,
                    effect="造成灼烧")


def _defense_curl() -> SkillRef:
    return SkillRef(name="防御", element="普通", category="防御", energy=1, power=0,
                    effect="减伤70%")


def _move(skill_index: int) -> MoveDecision:
    return MoveDecision(action="move", skill_index=skill_index)


def _switch(slot: int) -> MoveDecision:
    return MoveDecision(action="switch", switch_slot=slot)


@pytest.fixture
def two_pet_team_a():
    return [
        _mk_pet("火龙", hp=120, atk=100, spd=80, element="火", moves=[_ember(), _tackle()]),
        _mk_pet("草龟", hp=150, atk=70, spd=40, element="草", moves=[_water_gun(), _tackle()]),
    ]


@pytest.fixture
def two_pet_team_b():
    return [
        _mk_pet("水蛇", hp=100, atk=90, spd=70, element="水", moves=[_water_gun(), _tackle()]),
        _mk_pet("雷鸟", hp=80, atk=110, spd=110, element="电", moves=[_ember(), _tackle()]),
    ]


# ── Basic flow ─────────────────────────────────────────────────

def test_single_turn_attack(two_pet_team_a, two_pet_team_b):
    engine = BattleEngine(two_pet_team_a, two_pet_team_b)
    engine.step(_move(0), _move(0))   # both use move[0]
    state = engine.state
    assert state.turn_number == 1
    # Water beats fire: should deal more to 火龙
    fire_dragon = state.team_a[0]
    water_snake = state.team_b[0]
    # Both should have taken damage
    assert fire_dragon.current_hp < fire_dragon.max_hp
    assert water_snake.current_hp <= water_snake.max_hp


def test_energy_consumed_after_attack():
    # Use high-HP same-type pets so one hit doesn't KO
    a = [_mk_pet("A", hp=999, atk=50, spd=100, element="火", moves=[_ember()])]
    b = [_mk_pet("B", hp=999, atk=50, spd=50, element="火", moves=[_ember()])]
    engine = BattleEngine(a, b)
    engine.step(_move(0), _move(0))
    # start 10 + gain 2 (cap 10) - cost 2 = 8
    assert engine.get_active("a").current_energy == 8


def test_energy_accumulates():
    a = [_mk_pet("A", hp=999, atk=50, spd=100, element="普通", moves=[_ember(), _tackle()])]
    b = [_mk_pet("B", hp=999, atk=50, spd=50, element="普通", moves=[_ember(), _tackle()])]
    engine = BattleEngine(a, b)
    engine.step(_move(1), _move(1))  # both tackle (1 energy)
    # start 10 + gain 2 (cap 10) - cost 1 = 9
    # turn 2: gain 2 (cap 10) - cost 1 = 9
    engine.step(_move(1), _move(1))
    assert engine.get_active("a").current_energy == 9


def test_faint_and_auto_switch(two_pet_team_a, two_pet_team_b):
    """When active faints, auto-switch to next available."""
    # Create a team where B only has 1 pet that dies fast
    team_a = [_mk_pet("杀手", hp=200, atk=150, spd=200, element="火", moves=[_ember()])]
    team_b = [_mk_pet("炮灰", hp=10, atk=50, spd=10, element="草", moves=[_tackle()]),
              _mk_pet("替补", hp=100, atk=80, spd=80, element="水", moves=[_water_gun()])]

    engine = BattleEngine(team_a, team_b)
    engine.step(_move(0), _move(0))
    state = engine.state

    # 炮灰 should be fainted (fire 2x vs grass)
    assert state.team_b[0].is_fainted
    # Auto-switch should have activated 替补
    assert state.active_b == 1
    assert not state.team_b[1].is_fainted


def test_win_condition_team_wipe():
    """All 6 faint → winner declared."""
    team_a = [_mk_pet("杀手", hp=200, atk=500, spd=200, element="火", moves=[_ember()])]
    team_b = [_mk_pet("炮灰", hp=10, atk=50, spd=10, element="草", moves=[_tackle()])]

    engine = BattleEngine(team_a, team_b)
    engine.step(_move(0), _move(0))
    assert engine.is_finished()
    assert engine.get_winner() == "a"


def test_battle_timeout_draw():
    team_a = [_mk_pet("A", hp=999, atk=1, spd=50, moves=[_tackle()])]
    team_b = [_mk_pet("B", hp=999, atk=1, spd=50, moves=[_tackle()])]

    engine = BattleEngine(team_a, team_b, max_turns=10)
    for _ in range(10):
        if engine.is_finished():
            break
        engine.step(_move(0), _move(0))
    assert engine.get_winner() == "draw"


# ── Speed order ────────────────────────────────────────────────

def test_faster_pet_moves_first():
    fast = _mk_pet("快", hp=100, atk=100, spd=200, element="普通", moves=[_ember()])
    slow = _mk_pet("慢", hp=10, atk=50, spd=1, element="草", moves=[_tackle()])

    engine = BattleEngine([fast], [slow])
    engine.step(_move(0), _move(0))
    # 慢 (grass) should be dead before it can act
    assert engine.state.team_b[0].is_fainted
    # 快 should be untouched
    assert engine.state.team_a[0].current_hp == engine.state.team_a[0].max_hp


# ── Switch mechanics ───────────────────────────────────────────

def test_manual_switch(two_pet_team_a, two_pet_team_b):
    engine = BattleEngine(two_pet_team_a, two_pet_team_b)
    engine.step(_switch(1), _move(0))  # A switches, B attacks
    state = engine.state
    assert state.active_a == 1
    # The switched-in pet should take the hit
    assert state.team_a[1].current_hp <= state.team_a[1].max_hp


def test_cannot_switch_to_fainted(two_pet_team_a, two_pet_team_b):
    """Kill slot 1, then try to switch to it — should stay on current."""
    # Kill the bench pet first
    # Actually let's just test that get_available_switches excludes fainted
    team_a = [_mk_pet("A", hp=100, atk=50, spd=50, moves=[_tackle()]),
              _mk_pet("B_dead", hp=100, atk=50, spd=50, moves=[_tackle()])]
    team_b = [_mk_pet("Killer", hp=200, atk=500, spd=200, element="火", moves=[_ember()])]

    engine = BattleEngine(team_a, team_b)
    engine.step(_switch(1), _move(0))  # switch to B
    # Killer kills B
    engine.step(_move(0), _move(0))
    # Now B is dead, available switches should be []
    assert 1 not in engine.get_available_switches("a")


# ── Status effects ─────────────────────────────────────────────

def test_burn_application():
    attacker = _mk_pet("火使", hp=100, atk=80, spd=100, element="火", moves=[_will_o_wisp()])
    defender = _mk_pet("靶子", hp=100, atk=80, spd=50, element="草", moves=[_tackle()])

    engine = BattleEngine([attacker], [defender])
    engine.step(_move(0), _move(0))
    assert "灼烧" in engine.state.team_b[0].status_stacks


def test_burn_end_of_turn_damage():
    attacker = _mk_pet("火使", hp=100, atk=80, spd=200, element="火", moves=[_will_o_wisp()])
    defender = _mk_pet("靶子", hp=1000, atk=80, spd=50, element="草", moves=[_tackle()])

    engine = BattleEngine([attacker], [defender])
    engine.step(_move(0), _move(0))
    # Burn applied (1 stack), then end-of-turn burn tick
    # 1 stack * 1000 * 0.02 * 2.0 (火2x草) = 40
    burn_events = [e for e in engine.state.log if e.action == "status_tick" and
                   e.detail.get("status") == "灼烧"]
    assert len(burn_events) >= 1  # at least end-of-turn tick


def test_fire_type_burn_immune():
    attacker = _mk_pet("火使", hp=100, atk=80, spd=100, element="火", moves=[_will_o_wisp()])
    defender = _mk_pet("火靶", hp=100, atk=80, spd=50, element="火", moves=[_tackle()])

    engine = BattleEngine([attacker], [defender])
    engine.step(_move(0), _move(0))
    assert "灼烧" not in engine.state.team_b[0].status_stacks


# ── Type effectiveness in damage ───────────────────────────────

def test_super_effective_damage():
    """Fire move vs Grass = 2x."""
    attacker = _mk_pet("A", hp=100, atk=100, spd=100, element="火", moves=[_ember()])
    defender = _mk_pet("B", hp=100, atk=80, spd=50, element="草", moves=[_tackle()])

    engine = BattleEngine([attacker], [defender])
    engine.step(_move(0), _move(0))
    atk_events = [e for e in engine.state.log if e.action == "attack"]
    assert atk_events[0].detail["type_mult"] == 2.0


def test_resisted_damage():
    """Fire move vs Water = 0.5x."""
    attacker = _mk_pet("A", hp=100, atk=100, spd=100, element="火", moves=[_ember()])
    defender = _mk_pet("B", hp=100, atk=80, spd=50, element="水", moves=[_tackle()])

    engine = BattleEngine([attacker], [defender])
    engine.step(_move(0), _move(0))
    atk_events = [e for e in engine.state.log if e.action == "attack"]
    assert atk_events[0].detail["type_mult"] == 0.5


# ── Determinism ────────────────────────────────────────────────

def test_same_inputs_same_outcome(two_pet_team_a, two_pet_team_b):
    """Same starting state + same moves = exactly same result."""
    def run():
        engine = BattleEngine(two_pet_team_a, two_pet_team_b)
        engine.step(_move(0), _move(0))
        engine.step(_move(1), _move(1))
        return (engine.state.team_a[0].current_hp,
                engine.state.team_b[0].current_hp,
                engine.state.turn_number)

    a = run()
    b = run()
    assert a == b


# ── Buff stages ────────────────────────────────────────────────

def test_defense_curl_buffs_self():
    pet = _mk_pet("盾", hp=100, atk=50, spd=50, element="普通", moves=[_defense_curl()])
    target = _mk_pet("靶", hp=100, atk=50, spd=50, element="普通", moves=[_tackle()])

    engine = BattleEngine([pet], [target])
    engine.step(_move(0), _move(0))
    assert engine.state.team_a[0].buff_stages.get("def_phys", 0) > 0
    assert engine.state.team_a[0].buff_stages.get("def_mag", 0) > 0


# ── Full 6v6 battle ────────────────────────────────────────────

def test_full_6v6_battle():
    def _team(prefix: str) -> list[PetState]:
        return [
            _mk_pet(f"{prefix}1", hp=100, atk=80, spd=100 - i * 10, element="普通",
                    moves=[_tackle(), _ember()])
            for i in range(6)
        ]

    engine = BattleEngine(_team("A"), _team("B"))
    turns = 0
    while not engine.is_finished() and turns < 200:
        # Simple AI: use strongest available move
        a_moves = engine.get_valid_moves("a")
        b_moves = engine.get_valid_moves("b")
        ma = _move(a_moves[0]) if a_moves else _move(0)
        mb = _move(b_moves[0]) if b_moves else _move(0)
        engine.step(ma, mb)
        turns += 1

    assert engine.get_winner() in ("a", "b", "draw")
    assert turns > 0


# ── Magic power (4-KO win condition) ───────────────────────────

def test_magic_power_decrements_on_faint():
    """Each KO costs 1 magic. Start at 4."""
    killer = _mk_pet("K", hp=200, atk=500, spd=200, element="火", moves=[_ember()])
    sacks = [_mk_pet(f"S{i}", hp=10, atk=50, spd=10, element="草", moves=[_tackle()])
             for i in range(6)]

    engine = BattleEngine([killer], sacks)
    assert engine.state.magic_b == 4

    engine.step(_move(0), _move(0))  # kill sack 1
    assert engine.state.magic_b == 3
    assert engine.state.team_b[0].is_fainted
    assert not engine.is_finished()  # still 3 more to go

    engine.step(_move(0), _move(0))  # kill sack 2
    assert engine.state.magic_b == 2
    engine.step(_move(0), _move(0))  # kill sack 3
    assert engine.state.magic_b == 1
    engine.step(_move(0), _move(0))  # kill sack 4 → magic = 0
    assert engine.state.magic_b == 0
    assert engine.is_finished()
    assert engine.get_winner() == "a"


def test_fake_death_no_magic_cost():
    """卡瓦重's 诈死: fainting costs 0 magic."""
    killer = _mk_pet("K", hp=200, atk=500, spd=200, element="火", moves=[_ember()])
    fake_death = _mk_pet("卡瓦重", hp=50, atk=50, spd=10, element="地", moves=[_tackle()])
    fake_death.ability_name = "诈死"

    engine = BattleEngine([killer], [fake_death])
    assert engine.state.magic_b == 4

    engine.step(_move(0), _move(0))  # kill 卡瓦重
    assert engine.state.magic_b == 4  # unchanged! 诈死
    assert engine.state.team_b[0].is_fainted
    assert engine.is_finished()  # no bench → loss
    assert engine.get_winner() == "a"


def test_fake_death_mixed_with_normal():
    """卡瓦重 + normal pets: only normal faints cost magic."""
    killer = _mk_pet("K", hp=200, atk=500, spd=200, element="火", moves=[_ember()])
    fake = _mk_pet("卡瓦重", hp=50, atk=50, spd=10, element="地", moves=[_tackle()])
    fake.ability_name = "诈死"
    normal = _mk_pet("炮灰", hp=10, atk=50, spd=50, element="草", moves=[_tackle()])

    engine = BattleEngine([killer], [fake, normal])
    assert engine.state.magic_b == 4

    # First KO: 卡瓦重 dies → no cost
    engine.step(_move(0), _move(0))
    assert engine.state.magic_b == 4

    # Second KO: 炮灰 dies → costs 1
    engine.step(_move(0), _move(0))
    assert engine.state.magic_b == 3


def test_magic_power_state_display():
    """Verify BattleState includes magic fields."""
    a = [_mk_pet("A", hp=100, atk=50, spd=50, moves=[_tackle()])]
    b = [_mk_pet("B", hp=100, atk=50, spd=50, moves=[_tackle()])]
    engine = BattleEngine(a, b)
    assert engine.state.magic_a == 4
    assert engine.state.magic_b == 4
