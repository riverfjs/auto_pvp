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
    """Reject used :class:`effect_gaps` rows that have not been acknowledged.

    Phase 3 introduced ``roco/compiler/rules/effect_gap_acknowledgements.jsonl``
    as a parallel audit axis.  A used gap row passes this gate iff it has a
    matching acknowledgement (canonical key); the gate also rejects stale
    acks (acks that no longer match any used gap) and over-broad acks
    (acks whose match count differs from the declared expectation), so the
    ack table stays in lockstep with the gap reality and burn-down is forced
    instead of silently drifting.
    """
    from roco.compiler.effect_codegen.acknowledgements_loader import (
        canonical_gap_key_from_row,
        load_acknowledgements,
    )

    # A totally empty ``effect_gaps`` table means the caller is operating on
    # a synthetic / fixture DB that never ran the canonical import.  In
    # that environment the real acknowledgements file is unrelated to the
    # DB state, so skip the gate entirely instead of erroring on stale
    # acks the test never set up.
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
    gap_key_to_row: dict[str, tuple] = {}
    for row in rows:
        key = canonical_gap_key_from_row({
            "source_type": row[0],
            "source_name": row[1],
            "primitive": row[2],
            "timing_code": row[3],
            "params_json": row[4],
            "reason": row[5],
        })
        gap_key_to_row[key] = row
    gap_keys = set(gap_key_to_row)

    acks = load_acknowledgements()
    ack_keys: set[str] = set()
    ack_key_to_line: dict[str, int] = {}
    ack_match_counts: dict[int, int] = {}  # line_no -> matches against gap rows
    ack_expected: dict[int, int] = {}      # line_no -> expected match count
    ack_allow_stale: dict[int, bool] = {}
    for ack in acks:
        keys = ack.expected_canonical_keys
        ack_expected[ack.line_no] = len(keys)
        ack_allow_stale[ack.line_no] = ack.allow_stale
        ack_match_counts[ack.line_no] = sum(1 for k in keys if k in gap_keys)
        for key in keys:
            ack_keys.add(key)
            ack_key_to_line.setdefault(key, ack.line_no)

    errors: list[str] = []

    # Direction A: unack'd used gap
    unacked = sorted(gap_keys - ack_keys)
    if unacked:
        sample = []
        for key in unacked[:20]:
            row = gap_key_to_row[key]
            sample.append(
                f"{row[0]}:{row[1]} primitive={row[2]} timing={row[3]} "
                f"reason={row[5]} used={row[6]}"
            )
        errors.append(
            f"{len(unacked)} used effect_gaps row(s) have no acknowledgement; "
            f"add a row to roco/compiler/rules/effect_gap_acknowledgements.jsonl "
            f"or implement the gap first. Sample: " + "; ".join(sample)
        )

    # Direction B: stale ack
    stale = sorted(ack_keys - gap_keys)
    if stale:
        # Filter out ack rows that opt in to ``allow_stale``.  An ack with
        # all of its expected matches missing AND allow_stale=true is
        # tolerated; partial mismatches still fail.
        truly_stale_lines: dict[int, list[str]] = {}
        for key in stale:
            line_no = ack_key_to_line[key]
            if ack_allow_stale.get(line_no):
                continue
            truly_stale_lines.setdefault(line_no, []).append(key)
        if truly_stale_lines:
            sample = [
                f"line {line} (keys {keys[:3]})"
                for line, keys in list(truly_stale_lines.items())[:20]
            ]
            errors.append(
                f"{len(truly_stale_lines)} acknowledgement row(s) no longer match any "
                f"used effect_gaps row; remove the stale entries (or implement them) so "
                f"burn-down progress is reflected. Sample: " + "; ".join(sample)
            )

    # Direction C: over-/under-match
    mismatched: list[str] = []
    for line_no, expected in ack_expected.items():
        actual = ack_match_counts.get(line_no, 0)
        if ack_allow_stale.get(line_no) and actual == 0:
            continue  # opt-in stale row is tolerated above
        if actual != expected:
            mismatched.append(
                f"line {line_no}: expected {expected} match(es), got {actual}"
            )
    if mismatched:
        errors.append(
            f"{len(mismatched)} acknowledgement row(s) have a match count that "
            f"differs from their declared expectation; refine gap_match or "
            f"declare allow_multi_match with the full expected_matches list. "
            "Sample: " + "; ".join(mismatched[:20])
        )

    if errors:
        raise RuntimeError("; ".join(errors))


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
