"""Post-import validation checks for the normalized SQLite data store."""

from __future__ import annotations

import sqlite3


def assert_no_blocking_effect_gaps(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT source_type, source_name, primitive, reason, used_count
        FROM effect_gaps
        WHERE used_count > 0
        ORDER BY used_count DESC, source_type, source_name
        LIMIT 20
        """
    ).fetchall()
    if not rows:
        return
    details = ", ".join(f"{row[0]}:{row[1]} used={row[4]} reason={row[3]}" for row in rows)
    raise RuntimeError(f"used skills/abilities have unclassified effect gaps: {details}")


def assert_no_missing_leader_transforms(conn: sqlite3.Connection) -> None:
    magic = conn.execute("SELECT id FROM bloodline_magics WHERE code = 'leader_transform'").fetchone()
    bloodline = conn.execute("SELECT id FROM bloodlines WHERE code = 'leader'").fetchone()
    if magic is None or bloodline is None:
        return
    rows = conn.execute(
        """
        SELECT t.title, tp.pet_name
        FROM teams t
        JOIN team_pets tp ON tp.team_id = t.id
        WHERE t.bloodline_magic_id = ?
          AND tp.bloodline_id = ?
          AND tp.pet_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM pet_transforms pt WHERE pt.source_pet_id = tp.pet_id
          )
        ORDER BY t.title, tp.pet_name
        LIMIT 20
        """,
        (int(magic[0]), int(bloodline[0])),
    ).fetchall()
    if not rows:
        return
    details = ", ".join(f"{row[0]}:{row[1]}" for row in rows)
    raise RuntimeError(f"leader bloodline pets have no leader transform mapping: {details}")
