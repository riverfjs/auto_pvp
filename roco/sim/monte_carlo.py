"""Monte Carlo PVP battle simulator.

Loads teams from SQLite, runs N simulated battles with different AI policies,
and produces win-rate matrices.

Usage:
    python scripts/monte_carlo.py                     # run all PVP matchups
    python scripts/monte_carlo.py --n 10              # 10 battles per matchup
    python scripts/monte_carlo.py --teams 3           # only first 3 teams
    python scripts/monte_carlo.py --policy greedy     # use GreedyPolicy for both sides
"""

from __future__ import annotations

import sqlite3
import random
import sys
import argparse
from collections import Counter
from roco.engine.battle import BattleEngine
from roco.engine.state import BattleState, MoveDecision, PetState, SkillRef
from roco.engine.damage import compute_stats
from roco.data.utils import DB_DIR
from roco.config.constants import DEFAULT_MAX_TURNS


# ── Team loading ───────────────────────────────────────────────

def load_pet_from_db(name: str, conn: sqlite3.Connection,
                     nature: str = "", ivs: list[str] | None = None,
                     move_names: list[str] | None = None,
                     bloodline: str = "") -> PetState | None:
    """Load a single pet from the database with full stats and moves."""
    row = conn.execute(
        "SELECT name, hp, atk_phys, atk_mag, def_phys, def_mag, speed, "
        "element_primary, ability_name, ability_desc "
        "FROM pets WHERE name = ?", (name,)
    ).fetchone()
    if not row:
        return None

    base_stats = compute_stats(
        hp=row["hp"],
        atk_phys=row["atk_phys"],
        atk_mag=row["atk_mag"],
        def_phys=row["def_phys"],
        def_mag=row["def_mag"],
        speed=row["speed"],
        nature=nature,
        ivs=ivs or [],
    )

    # Load skill data for the requested moves
    skills: list[SkillRef] = []
    if move_names:
        for mn in move_names:
            sk = conn.execute(
                "SELECT name, element, category, energy, power, effect, "
                "tags, weather_type, enemy_cost_up_amount, hp_cost_pct, "
                "permanent_hit_growth, permanent_power_growth "
                "FROM skills WHERE name = ?", (mn,)
            ).fetchone()
            if sk:
                # Tags and parsed fields come from DB (pre-classified at import time)
                tags_str = sk["tags"] or "" if "tags" in sk.keys() else ""
                sref = SkillRef(
                    name=sk["name"], element=sk["element"],
                    category=sk["category"], energy=sk["energy"],
                    power=sk["power"], effect=sk["effect"] or "",
                    tags=tags_str.split(",") if tags_str else [],
                    weather_type=sk["weather_type"] if "weather_type" in sk.keys() else "",
                    enemy_cost_up_amount=sk["enemy_cost_up_amount"] if "enemy_cost_up_amount" in sk.keys() else 0,
                    hp_cost_pct=sk["hp_cost_pct"] if "hp_cost_pct" in sk.keys() else 0.0,
                    permanent_hit_growth=sk["permanent_hit_growth"] if "permanent_hit_growth" in sk.keys() else 0,
                    permanent_power_growth=sk["permanent_power_growth"] if "permanent_power_growth" in sk.keys() else 0,
                )
                skills.append(sref)

    return PetState(
        name=name,
        base_stats=dict(base_stats),
        effective_stats=dict(base_stats),
        element_primary=row["element_primary"],
        bloodline=bloodline,
        nature=nature,
        ivs=ivs or [],
        moves=skills,
        ability_name=row["ability_name"] or "",
        ability_desc=row["ability_desc"] or "",
    )


def load_team_from_db(team_id: str, conn: sqlite3.Connection) -> list[PetState] | None:
    """Load a full 6-pet team from the database."""
    team = conn.execute(
        "SELECT id, title, bloodline_magic FROM teams WHERE id = ?", (team_id,)
    ).fetchone()
    if not team:
        return None

    slots = conn.execute(
        "SELECT slot, pet_name, name_short, bloodline, nature, ivs, "
        "move1, move2, move3, move4 "
        "FROM team_pets WHERE team_id = ? ORDER BY slot", (team_id,)
    ).fetchall()

    pets: list[PetState] = []
    for sl in slots:
        ivs_list = [v.strip() for v in sl["ivs"].split(",") if v.strip()] if sl["ivs"] else []
        moves = [m for m in [sl["move1"], sl["move2"], sl["move3"], sl["move4"]] if m]
        pet = load_pet_from_db(
            name=sl["pet_name"],
            conn=conn,
            nature=sl["nature"],
            ivs=ivs_list,
            move_names=moves,
            bloodline=sl["bloodline"],
        )
        if pet:
            pet.slot = sl["slot"]
            pets.append(pet)

    return pets if pets else None


def load_all_pvp_teams(conn: sqlite3.Connection) -> dict[str, tuple[str, list[PetState]]]:
    """Load all PVP teams. Returns {team_id: (title, [PetState, ...])}."""
    rows = conn.execute(
        "SELECT id, title FROM teams WHERE type = 'pvp' ORDER BY upload_date DESC"
    ).fetchall()
    result: dict[str, tuple[str, list[PetState]]] = {}
    for r in rows:
        pets = load_team_from_db(r["id"], conn)
        if pets:
            result[r["id"]] = (r["title"], pets)
    return result


# ── Policy interface ───────────────────────────────────────────

class Policy:
    """Abstract move-selection strategy."""
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        raise NotImplementedError


class RandomPolicy(Policy):
    """Random valid move. Favors attacking moves (70% attack, 30% switch)."""
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        valid_moves = _get_valid_moves(state, team)
        available_switches = _get_switches(state, team)

        if random.random() < 0.7 and valid_moves:
            return MoveDecision(action="move", skill_index=random.choice(valid_moves))
        elif available_switches:
            return MoveDecision(action="switch", switch_slot=random.choice(available_switches))
        elif valid_moves:
            return MoveDecision(action="move", skill_index=random.choice(valid_moves))
        else:
            return MoveDecision(action="move", skill_index=0)  # will be skipped


class GreedyPolicy(Policy):
    """Pick the move with the highest base power (ignoring type matchups)."""
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        pet = _get_active(state, team)
        valid = _get_valid_moves(state, team)
        if not valid:
            return MoveDecision(action="move", skill_index=0)
        best = max(valid, key=lambda i: pet.moves[i].power)
        return MoveDecision(action="move", skill_index=best)


class TypeAdvantagePolicy(Policy):
    """Pick the move with the best type matchup against the opponent."""
    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        from roco.damage import get_type_multiplier

        pet = _get_active(state, team)
        opp_team = "b" if team == "a" else "a"
        opponent = _get_active(state, opp_team)
        valid = _get_valid_moves(state, team)
        if not valid:
            return MoveDecision(action="move", skill_index=0)

        def score(idx: int) -> float:
            return get_type_multiplier(
                pet.moves[idx].element, opponent.defender_types
            )

        best = max(valid, key=score)
        return MoveDecision(action="move", skill_index=best)


class FixedPolicy(Policy):
    """Always use moves in order: 0, 1, 2, 3, cycle. For debugging."""
    def __init__(self):
        self._counter: dict[str, int] = {}

    def select_move(self, state: BattleState, team: str) -> MoveDecision:
        key = team
        idx = self._counter.get(key, 0)
        self._counter[key] = idx + 1
        pet = _get_active(state, team)
        return MoveDecision(action="move", skill_index=idx % len(pet.moves))


# ── Helpers ────────────────────────────────────────────────────

def _get_active(state: BattleState, team: str) -> PetState:
    idx = state.active_a if team == "a" else state.active_b
    return (state.team_a if team == "a" else state.team_b)[idx]


def _get_valid_moves(state: BattleState, team: str) -> list[int]:
    pet = _get_active(state, team)
    return [i for i, m in enumerate(pet.moves)
            if m.energy <= pet.current_energy]


def _get_switches(state: BattleState, team: str) -> list[int]:
    pets = state.team_a if team == "a" else state.team_b
    active = state.active_a if team == "a" else state.active_b
    return [i for i, p in enumerate(pets) if i != active and not p.is_fainted]


POLICIES: dict[str, type[Policy]] = {
    "random": RandomPolicy,
    "greedy": GreedyPolicy,
    "type": TypeAdvantagePolicy,
    "fixed": FixedPolicy,
}


# ── MC runner ──────────────────────────────────────────────────

def run_single_battle(
    team_a: list[PetState],
    team_b: list[PetState],
    policy_a: Policy,
    policy_b: Policy,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    """Run one battle. Returns {winner, turns, log}."""
    engine = BattleEngine(team_a, team_b, max_turns=max_turns)
    turns = 0
    while not engine.is_finished():
        ma = policy_a.select_move(engine.state, "a")
        mb = policy_b.select_move(engine.state, "b")
        engine.step(ma, mb)
        turns += 1
    return {
        "winner": engine.get_winner(),
        "turns": turns,
        "log": engine.state.log,
    }


def run_monte_carlo(
    team_a: list[PetState],
    team_b: list[PetState],
    policy_a: Policy,
    policy_b: Policy,
    n: int = 100,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    """Run N battles. Returns win rate stats."""
    wins: Counter = Counter()
    turns_list: list[int] = []

    for _ in range(n):
        result = run_single_battle(team_a, team_b, policy_a, policy_b, max_turns)
        w = result["winner"]
        wins[w] += 1
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
    teams: dict[str, tuple[str, list[PetState]]],
    n: int = 50,
    policy_name: str = "random",
) -> dict:
    """Run every team vs every team. Returns a results matrix."""
    team_ids = list(teams.keys())
    policy_cls = POLICIES[policy_name]
    results: dict = {"teams": [], "matrix": {}}

    for tid in team_ids:
        title, _ = teams[tid]
        results["teams"].append({"id": tid, "title": title})

    total = len(team_ids) * (len(team_ids))
    done = 0
    for i, tid_a in enumerate(team_ids):
        title_a, team_a = teams[tid_a]
        for j, tid_b in enumerate(team_ids):
            done += 1
            if tid_a == tid_b:
                continue

            key = f"{tid_a[:8]} vs {tid_b[:8]}"
            mc = run_monte_carlo(team_a, teams[tid_b][1],
                                 policy_cls(), policy_cls(), n=n)
            results["matrix"][key] = {
                "team_a": title_a,
                "team_b": teams[tid_b][0],
                "win_rate_a": round(mc["win_rate_a"], 3),
                "draws": mc["draws"],
                "avg_turns": round(mc["avg_turns"], 1),
            }
            perc = done / total * 100
            print(f"[{done}/{total}] {key}: {mc['win_rate_a']:.1%}", flush=True)

    return results


# ── Main ───────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo PVP battle simulator")
    parser.add_argument("--n", type=int, default=10, help="Battles per matchup")
    parser.add_argument("--teams", type=int, default=0, help="Limit to first N teams")
    parser.add_argument("--policy", type=str, default="random",
                        choices=list(POLICIES), help="AI policy for both sides")
    parser.add_argument("--db", type=str, default=str(DB_DIR / "data.db"))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    print("Loading PVP teams...")
    teams = load_all_pvp_teams(conn)
    print(f"Loaded {len(teams)} teams")

    if args.teams > 0:
        keys = list(teams.keys())[:args.teams]
        teams = {k: teams[k] for k in keys}
        print(f"Using {len(teams)} teams")

    print(f"Running {args.n} battles per matchup (policy={args.policy})...")
    results = run_matchup_matrix(teams, n=args.n, policy_name=args.policy)

    # Print summary
    print("\n=== Win Rate Matrix ===")
    header = f"{'Team A':<16} {'Team B':<16} {'WR(A)':>8}"
    print(header)
    print("-" * len(header))
    for key, val in sorted(results["matrix"].items(),
                           key=lambda x: -x[1]["win_rate_a"]):
        if val["win_rate_a"] >= 0.50:
            print(f"{val['team_a']:<16} {val['team_b']:<16} {val['win_rate_a']:>7.1%}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
