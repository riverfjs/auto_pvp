"""Optional comparison report against a local NRC_AI checkout.

This tool is intentionally outside the default build path. It does not import
or execute NRC_AI modules; it only scans local source text to help decide which
project-owned manual rules should be written next.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

from roco.data.utils import CANONICAL_DIR

_DICT_KEY_RE = re.compile(r'^\s*"([^"]+)"\s*:\s*\[', re.MULTILINE)


def project_report(nrc_root: Path) -> dict[str, object]:
    skills = _load_project("skills.jsonl")
    abilities = _load_project("abilities.jsonl")
    nrc_skills = _nrc_names(nrc_root, ("src/effect_data.py", "src/skill_effects_generated.py"))

    skill_gaps = _gap_names(skills)
    ability_gaps = _gap_names(abilities)
    project_skill_names = set(skills)
    return {
        "nrc_root": str(nrc_root),
        "project_skill_count": len(skills),
        "project_ability_count": len(abilities),
        "nrc_skill_name_count": len(nrc_skills),
        "matched_skill_count": len(project_skill_names & nrc_skills),
        "project_skill_gaps": sorted(skill_gaps),
        "project_ability_gaps": sorted(ability_gaps),
        "project_skill_gaps_present_in_nrc": sorted(skill_gaps & nrc_skills),
        "nrc_only_skill_names": sorted(nrc_skills - project_skill_names),
    }


def _load_project(filename: str) -> dict[str, dict]:
    path = CANONICAL_DIR / filename
    rows: dict[str, dict] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        name = str(row.get("name", "")).strip()
        if name:
            rows[name] = row
    return rows


def _gap_names(rows: dict[str, dict]) -> set[str]:
    return {
        name
        for name, row in rows.items()
        if (row.get("classification") or {}).get("status") == "needs_manual"
    }


def _nrc_names(root: Path, rels: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for rel in rels:
        path = root / rel
        if not path.exists():
            continue
        names.update(_DICT_KEY_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return names


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nrc-root", type=Path, default=Path("/Users/River/Documents/Code/NRC_AI"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = project_report(args.nrc_root)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
