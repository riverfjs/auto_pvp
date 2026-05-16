"""Monte Carlo PVP battle simulator backed by the runtime catalog."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter
from dataclasses import replace

from roco.config.constants import DEFAULT_MAX_TURNS
from roco.data.catalog import RuntimeCatalog, compile_catalog
from roco.data.utils import DB_DIR
from roco.engine.battle import BattleEngine
from roco.engine.damage import compute_stats, get_type_multiplier
from roco.engine.state import BattleState, MoveDecision, PersistentPet, Stats


class Policy:
    """Abstract move-selection strategy."""
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        raise NotImplementedError


class RandomPolicy(Policy):
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        valid_moves = _get_valid_moves(state, team)
        switches = _get_switches(state, team)
        if random.random() < 0.7 and valid_moves:
            return MoveDecision("move", skill_index=random.choice(valid_moves))
        if switches:
            return MoveDecision("switch", switch_slot=random.choice(switches))
        return MoveDecision("move", skill_index=random.choice(valid_moves) if valid_moves else 0)


class GreedyPolicy(Policy):
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        pet = _get_active(state, team)
        valid = _get_valid_moves(state, team)
        if not valid:
            return MoveDecision("move", skill_index=0)
        return MoveDecision("move", skill_index=max(valid, key=lambda i: pet.persistent.moves[i].power))


class TypeAdvantagePolicy(Policy):
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        pet = _get_active(state, team)
        opponent = _get_active(state, "b" if team == "a" else "a")
        valid = _get_valid_moves(state, team)
        if not valid:
            return MoveDecision("move", skill_index=0)
        best = max(valid, key=lambda i: get_type_multiplier(pet.persistent.moves[i].element, opponent.elements))
        return MoveDecision("move", skill_index=best)


class FixedPolicy(Policy):
    def __init__(self):
        self._counter: dict[str, int] = {}

    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        pet = _get_active(state, team)
        idx = self._counter.get(team, 0)
        self._counter[team] = idx + 1
        return MoveDecision("move", skill_index=idx % max(1, len(pet.persistent.moves)))


POLICIES: dict[str, type[Policy]] = {
    "random": RandomPolicy,
    "greedy": GreedyPolicy,
    "type": TypeAdvantagePolicy,
    "fixed": FixedPolicy,
}


def _stat_tuple(base: dict[str, int]) -> tuple[int, int, int, int, int, int]:
    return (
        base["hp"], base["atk_phys"], base["atk_mag"],
        base["def_phys"], base["def_mag"], base["speed"],
    )


def _build_team_pet(catalog: RuntimeCatalog, row: sqlite3.Row, skill_names: list[str]) -> PersistentPet | None:
    data = catalog.pets_by_id.get(row["pet_id"]) or catalog.pets_by_name.get(row["pet_name"])
    if not data:
        return None
    base = compute_stats(
        hp=data.stat(Stats.HP),
        atk_phys=data.stat(Stats.ATK_PHYS),
        atk_mag=data.stat(Stats.ATK_MAG),
        def_phys=data.stat(Stats.DEF_PHYS),
        def_mag=data.stat(Stats.DEF_MAG),
        speed=data.stat(Stats.SPEED),
        nature=row["nature"] or "",
        ivs=json.loads(row["ivs_json"] or "[]"),
    )
    moves = tuple(catalog.skills_by_name[name] for name in skill_names if name in catalog.skills_by_name)
    if not moves:
        moves = tuple(catalog.skills_by_id[sid] for sid in catalog.pet_skill_ids.get(data.pet_id, ())[:4])
    return PersistentPet(
        name=data.name,
        stats=_stat_tuple(base),
        types=data.types,
        moves=moves,
        data_id=data.pet_id,
        ability_id=data.ability_id,
        ability_name=data.ability_name,
        ability_desc=data.ability_desc,
        bloodline=row["bloodline"] or "",
        nature=row["nature"] or "",
        ivs=json.loads(row["ivs_json"] or "[]"),
    )


def load_team_from_db(team_id: str, conn: sqlite3.Connection, catalog: RuntimeCatalog) -> list[PersistentPet] | None:
    slots = conn.execute(
        "SELECT id, slot, pet_id, pet_name, bloodline, nature, ivs_json "
        "FROM team_pets WHERE team_id = ? ORDER BY slot",
        (team_id,),
    ).fetchall()
    team: list[PersistentPet] = []
    for slot in slots:
        skill_rows = conn.execute(
            "SELECT skill_name FROM team_pet_skills WHERE team_pet_id = ? ORDER BY slot",
            (slot["id"],),
        ).fetchall()
        pet = _build_team_pet(catalog, slot, [r["skill_name"] for r in skill_rows])
        if pet:
            team.append(pet)
    return team or None


def load_all_pvp_teams(conn: sqlite3.Connection, catalog: RuntimeCatalog) -> dict[str, tuple[str, list[PersistentPet]]]:
    rows = conn.execute(
        "SELECT id, title FROM teams WHERE team_type = 'pvp' ORDER BY upload_date DESC"
    ).fetchall()
    result: dict[str, tuple[str, list[PersistentPet]]] = {}
    for row in rows:
        pets = load_team_from_db(row["id"], conn, catalog)
        if pets:
            result[row["id"]] = (row["title"], pets)
    return result


def _get_active(state: BattleState, team: str):
    idx = state.active_a if team == "a" else state.active_b
    return (state.team_a if team == "a" else state.team_b)[idx]


def _get_valid_moves(state: BattleState, team: str) -> list[int]:
    pet = _get_active(state, team)
    return [i for i, move in enumerate(pet.persistent.moves) if move.energy <= pet.current_energy]


def _get_switches(state: BattleState, team: str) -> list[int]:
    pets = state.team_a if team == "a" else state.team_b
    active = state.active_a if team == "a" else state.active_b
    return [i for i, pet in enumerate(pets) if i != active and not pet.is_fainted]


def run_single_battle(
    team_a: list[PersistentPet],
    team_b: list[PersistentPet],
    policy_a: Policy,
    policy_b: Policy,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    engine = BattleEngine(_clone_team(team_a), _clone_team(team_b), max_turns=max_turns)
    turns = 0
    while not engine.is_finished():
        engine.step(policy_a.select_move(engine.state, "a"), policy_b.select_move(engine.state, "b"))
        turns += 1
    return {"winner": engine.get_winner(), "turns": turns, "log": engine.state.log}


def _clone_team(team: list[PersistentPet]) -> list[PersistentPet]:
    cloned: list[PersistentPet] = []
    for pet in team:
        cloned.append(PersistentPet(
            name=pet.name,
            stats=pet.stats,
            types=pet.types,
            moves=tuple(replace(move) for move in pet.moves),
            data_id=pet.data_id,
            ability_id=pet.ability_id,
            ability_name=pet.ability_name,
            ability_desc=pet.ability_desc,
            ability_tags=list(pet.ability_tags),
            bloodline=pet.bloodline,
            nature=pet.nature,
            ivs=list(pet.ivs),
        ))
    return cloned


def run_monte_carlo(
    team_a: list[PersistentPet],
    team_b: list[PersistentPet],
    policy_a: Policy,
    policy_b: Policy,
    n: int = 100,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    wins: Counter = Counter()
    turns_list: list[int] = []
    for _ in range(n):
        result = run_single_battle(team_a, team_b, policy_a, policy_b, max_turns)
        wins[result["winner"]] += 1
        turns_list.append(result["turns"])
    return {
        "wins_a": wins.get("a", 0),
        "wins_b": wins.get("b", 0),
        "draws": wins.get("draw", 0),
        "win_rate_a": wins.get("a", 0) / n,
        "avg_turns": sum(turns_list) / len(turns_list),
        "n": n,
    }


def run_matchup_matrix(
    teams: dict[str, tuple[str, list[PersistentPet]]],
    n: int = 50,
    policy_name: str = "random",
) -> dict:
    team_ids = list(teams.keys())
    policy_cls = POLICIES[policy_name]
    results: dict = {"teams": [], "matrix": {}}
    for tid in team_ids:
        results["teams"].append({"id": tid, "title": teams[tid][0]})

    total = len(team_ids) * len(team_ids)
    done = 0
    for tid_a in team_ids:
        title_a, team_a = teams[tid_a]
        for tid_b in team_ids:
            done += 1
            if tid_a == tid_b:
                continue
            key = f"{tid_a[:8]} vs {tid_b[:8]}"
            mc = run_monte_carlo(team_a, teams[tid_b][1], policy_cls(), policy_cls(), n=n)
            results["matrix"][key] = {
                "team_a": title_a,
                "team_b": teams[tid_b][0],
                "win_rate_a": round(mc["win_rate_a"], 3),
                "draws": mc["draws"],
                "avg_turns": round(mc["avg_turns"], 1),
            }
            print(f"[{done}/{total}] {key}: {mc['win_rate_a']:.1%}", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo PVP battle simulator")
    parser.add_argument("--n", type=int, default=10, help="Battles per matchup")
    parser.add_argument("--teams", type=int, default=0, help="Limit to first N teams")
    parser.add_argument("--policy", choices=list(POLICIES), default="random")
    parser.add_argument("--db", default=str(DB_DIR / "data.db"))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    catalog = compile_catalog(conn)
    teams = load_all_pvp_teams(conn, catalog)
    if args.teams > 0:
        teams = {k: teams[k] for k in list(teams)[:args.teams]}

    print(f"Loaded {len(teams)} PVP teams")
    print(f"Running {args.n} battles per matchup (policy={args.policy})...")
    results = run_matchup_matrix(teams, n=args.n, policy_name=args.policy)

    print("\n=== Win Rate Matrix ===")
    header = f"{'Team A':<16} {'Team B':<16} {'WR(A)':>8}"
    print(header)
    print("-" * len(header))
    for _key, val in sorted(results["matrix"].items(), key=lambda x: -x[1]["win_rate_a"]):
        if val["win_rate_a"] >= 0.50:
            print(f"{val['team_a']:<16} {val['team_b']:<16} {val['win_rate_a']:>7.1%}")
    conn.close()


if __name__ == "__main__":
    main()
