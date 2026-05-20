# Phase 4 Mark Tag Map Semantic Gap Audit

`roco/data/import_db.py:116` defines a hand-curated dict `_MARK_TAG_MAP`
that maps mark codes to integers, and `import_db.py:501` consumes those
integers as if they were `skill_effects.tag_code`. **The two
namespaces don't overlap** — the dict reads as a hidden semantic gap.
This phase documents what's wrong, why it doesn't blow up today, and
why we are *not* fixing it in Phase 4.

## 1. Actual semantics and consumption chain

`_MARK_TAG_MAP` (`roco/data/import_db.py:116-130`, 13 entries) maps a
mark `code` (`"poison"`, `"moisture"`, `"meteor"`, …) to one of three
**pak prefix** integers:

```python
"poison":   2007,   # STATUS_CONDITION family
"moisture": 2143,   # MARK_CHANGE family
"meteor":   2094,   # MARK_METEOR family
"dragon" / "wind" / "charge" / "solar" / "attack" / "slow"
  / "sluggish" / "spirit" / "thorn" / "momentum": 2143,
```

The single consumer (`roco/data/import_db.py:498-524`, inside
`_import_marks`) does:

```python
tag = _MARK_TAG_MAP.get(code)
...
for source in record.get("source_skills", ()) or ():
    sid = skill_lookup.get(skill_name)
    ...
    if not sid or tag is None:
        continue
    exists = conn.execute(
        "SELECT 1 FROM skill_effects WHERE skill_id = ? AND tag_code = ? LIMIT 1",
        (sid, tag),
    ).fetchone()
    if exists is None:
        gap_rows.append(_gap_row(
            "skill", skill_name, str(tag), None,
            {"mark": code, "description": source.get("description", "")},
            "mark_source_missing_effect",
        ))
```

`skill_effects.tag_code` is the **handler index** assigned in
`roco/generated/handler_indices.py` — values like
`H_METEOR_MARK = 41`, `H_POISON_MARK = 12`, etc.  Those handler
indices have nothing to do with pak prefixes: there is no overlap
between `{2007, 2094, 2143}` and the integer range of handler
indices.  In other words, the `WHERE tag_code = ?` lookup with
`tag in {2007, 2094, 2143}` will **never** match any row in
`skill_effects`.

## 2. Why this never blows up

`_data/canonical/marks.jsonl` currently has **12 rows, every one of
them with `source_skills: []`** (verified with a one-line script over
the canonical JSONL).

The outer `for source in record.get("source_skills", ()) or ():`
loop therefore runs zero iterations across every mark record.  The
dispatch using `_MARK_TAG_MAP` is reached only inside that loop, so
the dict's values never participate in any `SELECT` and never
contribute to `effect_gaps`.

A fresh `uv run python -m roco.data.build_db` confirms:

```
mark audit effect_gaps rows: 0
```

The dict is **inert** under current canonical data.

## 3. Why Phase 4 only writes this doc

Three options were considered before opening the phase:

1. **Delete `_MARK_TAG_MAP` + the dead branch.**  Today the audit
   gap is 0; after deletion it is still 0.  But removing the dict
   also removes the scaffolding that was apparently meant to drive
   audit alerts once `marks.jsonl.source_skills` starts shipping
   non-empty data.  Deleting it now pre-empts that future decision
   without the information needed to make it.

2. **Rewrite values to handler indices** (`"meteor" →
   H_METEOR_MARK = 41`, …).  Without any non-empty `source_skills`
   row in the canonical data we have nothing to verify the rewrite
   against; the dict would still match zero rows after the rewrite,
   so the test baseline (`mark audit effect_gaps = 0`) wouldn't
   change.  The choice of values becomes a guess.

3. **Document the gap and wait.**  When canonical data starts
   shipping non-empty `source_skills`, we'll know which mark
   records actually want to participate in skill-effect audit and
   can decide between (1) and (2) on real data.

Phase 4 takes option (3) deliberately: no code change beyond a
one-line comment above the dict pointing at this doc, no test
modifications.  Two different invariants together hold the current
behaviour in place and must not be confused:

* **Real canonical build**: `mark audit effect_gaps rows: 0`,
  because every row in `_data/canonical/marks.jsonl` ships
  `source_skills: []`.  A fresh `uv run python -m roco.data.build_db`
  reports this directly.
* **Synthetic test scaffolding**:
  `tests/test_data_pipeline.py::test_marks_import_only_audits_source_skills`
  feeds one mark record with a *non-empty* `source_skills` entry
  and asserts that the dispatch produces exactly one
  `effect_gaps` row (`gaps == 1`, with `primitive = '2143'`).
  That assertion is what locks the inert dict's current
  behaviour: when `source_skills` *is* non-empty, the prefix
  value flows into `effect_gaps` as-is even though
  `skill_effects.tag_code` is a different namespace.

Options (1) and (2) would each break the synthetic test:

* (1) Deleting the dict and its consumer makes
  `gaps == 1` impossible — the test would fail because no row
  would be inserted.
* (2) Rewriting values to handler indices changes the inserted
  `primitive` from `'2143'` to e.g. `'41'`, so the
  `WHERE primitive = '2143'` assertion would fail.

Option (3) preserves both invariants exactly, leaving the
decision for when real `source_skills` data exists.

## 4. Re-audit triggers

Re-open this doc and choose between options (1) and (2) when:

- any row in `_data/canonical/marks.jsonl` has a non-empty
  `source_skills` list, or
- `mark audit effect_gaps rows: 0` ceases to be the stable
  baseline (any non-zero count after `build_db` runs against
  fresh canonical input), or
- the handler-index range that `_MARK_TAG_MAP` was implicitly
  written against (`H_POISON_MARK` through `H_MOMENTUM_MARK`)
  is renamed or restructured.

Until one of those happens, the dict stays as-is and this doc is
the place to come back to.
