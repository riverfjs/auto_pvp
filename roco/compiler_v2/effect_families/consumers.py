"""Reverse-consumer index + team-used name resolution.

Build the ``effect_id → [consumer entry, ...]`` map from canonical skills/
abilities, and the set of skill / ability names that appear in any
``teams.jsonl`` row.  Both are used by :func:`.family_builder._build_family`
to populate sample consumers and the ``used_consumer_count`` bucket.
"""

from __future__ import annotations

from collections import defaultdict


def _collect_consumer(record: dict, kind: str) -> dict:
    """Project a skills/abilities canonical row into a compact consumer dict."""
    source_fields = record.get("source_fields") or {}
    if kind == "skill":
        source_desc = str(record.get("effect_text") or "")
    else:
        source_desc = str(record.get("description") or source_fields.get("desc") or "")
    return {
        "kind": kind,  # 'skill' / 'ability'
        "source_id": int(record.get("source_id") or source_fields.get("id") or 0),
        "name": str(record.get("name", "")),
        "desc": source_desc,
        "source_desc": source_desc,
    }


def _consumer_skill_results(record: dict) -> list[dict]:
    """Pick the skill_result / effect_list list from a canonical row."""
    source_fields = record.get("source_fields") or {}
    rows = source_fields.get("skill_result") or source_fields.get("effect_list") or []
    return [entry for entry in rows if isinstance(entry, dict) and entry.get("effect_id")]


def _build_consumer_index(
    skills: list[dict],
    abilities: list[dict],
) -> dict[int, list[dict]]:
    """``effect_id → [consumer entry, ...]`` — one entry per consuming skill/ability.

    Each consumer entry carries the original ``skill_result_entry`` so the
    catalog can show cast_moment / target / success_rate context.
    """
    out: dict[int, list[dict]] = defaultdict(list)
    for record, kind in [(s, "skill") for s in skills] + [(a, "ability") for a in abilities]:
        head = _collect_consumer(record, kind)
        for entry in _consumer_skill_results(record):
            eid = int(entry["effect_id"])
            out[eid].append({**head, "skill_result_entry": entry})
    return out


def _build_team_used(teams: list[dict], pets: list[dict]) -> tuple[set[str], set[str]]:
    """Return (team_used_skill_names, team_used_ability_names) by canonical name.

    Mirrors :func:`roco.data.import_db.import_teams` pet resolution: a team
    pet's full descriptive ``name`` (e.g. ``星光狮（月光能量的样子）``) often
    has no canonical match because pets.jsonl carries form-stripped names
    like ``星光狮``.  Fall back to the team pet's ``name_short`` so ability
    lookups don't drop ~22 form-suffixed pet abilities (化茧 / 电流刺激 …).
    """
    used_skill_names: set[str] = set()
    used_pet_lookup_keys: set[str] = set()
    for team in teams:
        for pet in team.get("pets") or []:
            full_name = str(pet.get("name", ""))
            short_name = str(pet.get("name_short", ""))
            if full_name:
                used_pet_lookup_keys.add(full_name)
            if short_name and short_name != full_name:
                used_pet_lookup_keys.add(short_name)
            for move in pet.get("moves") or []:
                if isinstance(move, str):
                    used_skill_names.add(move)
                elif isinstance(move, dict) and move.get("name"):
                    used_skill_names.add(str(move["name"]))
    # Canonical pet → ability: index by ``name`` AND ``display_name`` so the
    # name_short fallback chain can hit either key (parse_pak emits both for
    # form variants).
    ability_by_pet_name: dict[str, str] = {}
    for pet in pets:
        ability = pet.get("ability")
        if not ability:
            continue
        for key in (pet.get("name"), pet.get("display_name")):
            if key:
                ability_by_pet_name.setdefault(str(key), str(ability))
    used_ability_names = {
        ability_by_pet_name[name]
        for name in used_pet_lookup_keys
        if name in ability_by_pet_name
    }
    return used_skill_names, used_ability_names
