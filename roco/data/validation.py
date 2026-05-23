"""Post-import validation checks for the normalized SQLite data store."""

from __future__ import annotations

import sqlite3


def assert_no_kernel_noop_rows(conn: sqlite3.Connection) -> None:
    """Reject any ``skill_effects`` / ``ability_effects`` row with ``tag_code = 0``.

    H_NOOP (handler index 0) is the kernel-side dispatch sentinel —
    decoders must never produce it.  This is a defensive invariant
    check; if it ever fires, a decoder has regressed.
    """
    skill_rows = conn.execute(
        "SELECT s.name FROM skill_effects se JOIN skills s ON s.id = se.skill_id "
        "WHERE se.tag_code = 0 LIMIT 5"
    ).fetchall()
    ability_rows = conn.execute(
        "SELECT a.name FROM ability_effects ae JOIN abilities a ON a.id = ae.ability_id "
        "WHERE ae.tag_code = 0 LIMIT 5"
    ).fetchall()
    if not skill_rows and not ability_rows:
        return
    details = []
    if skill_rows:
        details.append("skills=" + ",".join(r[0] for r in skill_rows))
    if ability_rows:
        details.append("abilities=" + ",".join(r[0] for r in ability_rows))
    raise RuntimeError(
        "kernel noop rows leaked into runtime tables (tag_code=0); "
        + "; ".join(details)
    )


def assert_no_blocking_effect_gaps(conn: sqlite3.Connection) -> None:
    """Reject every used :class:`effect_gaps` row.

    Used gaps mean a team/pet/ability currently reachable by the runtime
    references pak semantics the kernel did not compile.  There is no
    acknowledgement layer anymore: implement the pak-defined logic or keep
    the build failing.
    """
    total_gap_rows = conn.execute("SELECT COUNT(*) FROM effect_gaps").fetchone()[0]
    if total_gap_rows == 0:
        return

    rows = conn.execute(
        """
        SELECT source_type, source_name, primitive, timing_code, params_json, reason, used_count
        FROM effect_gaps
        WHERE used_count > 0
        """
    ).fetchall()
    used_gap_rows = [
        {
            "source_type": row[0],
            "source_name": row[1],
            "primitive": row[2],
            "timing_code": row[3],
            "params_json": row[4],
            "reason": row[5],
            "used_count": row[6],
        }
        for row in rows
    ]

    if not used_gap_rows:
        return
    sample = []
    for row in used_gap_rows[:20]:
        sample.append(
            f"{row['source_type']}:{row['source_name']} primitive={row['primitive']} "
            f"timing={row['timing_code']} reason={row['reason']} used={row['used_count']}"
        )
    raise RuntimeError(
        f"{len(used_gap_rows)} used effect_gaps row(s) block build; "
        "implement the pak-defined logic instead of acknowledging or "
        "silently dropping them. Sample: " + "; ".join(sample)
    )


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
