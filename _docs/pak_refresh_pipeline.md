# Pak artifact refresh pipeline

One driver — `roco-refresh-artifacts` (equivalently `python -m roco.data.refresh_artifacts`) — chains the canonical commands you would otherwise run by hand whenever the pak data or codegen logic changes.

## When to run

| Trigger                                                            | Command                                                |
|--------------------------------------------------------------------|--------------------------------------------------------|
| `pak-public-kit/` updated (new pak dump)                           | `uv run roco-refresh-artifacts`                        |
| Changed compiler_v2/effect compiler logic                          | `uv run roco-refresh-artifacts`                        |
| CI / pre-commit cleanliness probe on a clean tree                  | `uv run roco-refresh-artifacts --check`                |
| Same plus functional check                                         | `uv run roco-refresh-artifacts --check --with-tests`   |

## The steps (canonical order)

1. **`roco.compiler_v2.gen_prefix_map`** — writes pak/Lua static files, handler / prefix / type-chart / weather / counter / buff-immunity tables under `roco/generated/`.
2. **`roco.data.build_db`** — rebuilds `_db/data.db` directly from pak-derived in-memory records, then writes `roco/generated/catalog_hot.py` and `roco/generated/catalog_debug.py`. **The kernel catalog is written by `build_db`, not by `gen_prefix_map`** — common gotcha.
3. **`roco.compiler_v2.build_effect_families`** — writes `roco/compiler_v2/rules/effect_families.jsonl` and `_docs/effect_family_audit.md`.
4. **`roco.compiler_v2.build_effect_families --check`** — stability self-check on step 3's output. Always runs; not toggled by the driver's `--check`.
5. **`roco.compiler_v2.pak_schema_audit`** — writes `_docs/pak_schema_audit.md`: read-only inventory of pak's structural axes (`EFFECT_CONF.effect_order`, `BUFFBASE_CONF.buffbase_order`) and a debt assessment of hand-written rules against those axes. Does not drive runtime behavior.
6. **`roco.compiler_v2.pak_schema_audit --check`** — stability self-check on step 5's output. Always runs; not toggled by the driver's `--check`.

Steps are subprocess-isolated. The driver exits with the first step's non-zero return code; subsequent steps are skipped.

## Two distinct workflows for `--check` vs. real pak updates

`--check` and "actually refreshing pak data" are not the same thing — they are separate workflows.

### `--check` is a clean-tree / CI cleanliness probe

After the pipeline finishes (and pytest if `--with-tests` is given), `--check` runs `git status --porcelain --` over a fixed set of output paths. If anything shows up — modified, staged, or untracked — the driver prints the porcelain output and exits 1.

Use it when:

- Verifying that committed artifacts match a fresh rebuild from current pak input.
- Pre-commit / pre-push: "did anything I forgot to commit slip through?"
- CI: "is the repo deterministic from pak?"

Do **not** use `--check` immediately after a real pak update — it will simply report the new diff and exit 1, which is the expected outcome of a real refresh, not an error.

### Real pak refresh: drop `--check`, review the diff, commit

For an actual data change:

```bash
uv run roco-refresh-artifacts                           # let it write new artifacts
git status -- roco/generated \
              roco/compiler_v2/rules/effect_families.jsonl \
              _docs/effect_family_audit.md \
              _docs/pak_schema_audit.md                # see what moved
git diff -- roco/generated \
            roco/compiler_v2/rules/effect_families.jsonl \
            _docs/effect_family_audit.md \
            _docs/pak_schema_audit.md                  # eyeball the diff
# inspect, decide, then stage and commit by hand
```

The driver intentionally does not stage or commit — diff review stays with the human.

## Per-path diff contract

The paths the `--check` probe watches:

| Path                                              | Written by step | Notes                                                                          |
|---------------------------------------------------|-----------------|--------------------------------------------------------------------------------|
| `roco/generated/`                                 | 1 + 2           | Step 1 writes static pak/Lua adapters and handler/prefix/type-chart/weather/counter tables; step 2 (`build_db`) overwrites `catalog_hot.py` and `catalog_debug.py`. |
| `roco/compiler_v2/rules/effect_families.jsonl`       | 3               | Generated audit catalog. Remaining rule files are migration/audit inputs, not handler dispatch sources. |
| `_docs/effect_family_audit.md`                    | 3               | Human-readable family audit; regenerates whenever families.jsonl does.         |
| `_docs/pak_schema_audit.md`                       | 5               | Schema mining report — `(type, effect_order)` and `buffbase_order` axes + hand-written-rule debt. Read-only; informs future family-decoder work but does not drive runtime. |

Outside the check scope:

- `_db/data.db` — written by step 3. Tracked by git, but by convention developers do not commit the modifications between releases. A clean refresh always re-writes the bytes, so including it in the check would mean `--check` could never return 0 after a real run. Excluded.
- `_audit/` — local-only, untracked.
- `roco/compiler_v2/rules/effect_gap_acknowledgements.jsonl` — remaining hand-edited migration/audit input. Handler dispatch, ability flags, and buff immunity are generated from pak/Lua facts plus engine `op_meta` declarations, not `exact_effects.jsonl`, `prefix_handlers.jsonl`, `buffbase_order_handlers.jsonl`, `ability_flags_from_effects.jsonl`, or `buff_immunity.jsonl`.

## What must not diff

A pipeline run (with no source changes) must leave all of these untouched:

- `roco/engine/kernel/**`
- `roco/common/**`
- `roco/compiler_v2/rules/*.jsonl` **except** `effect_families.jsonl`
- `tests/**`
- `pyproject.toml`, `README.md`, source code in `roco/compiler_v2/effect_codegen/**` / `roco/compiler_v2/**`

If any of these moves after a refresh, something has gone wrong upstream — either a non-pak source slipped into a generator, or hand-edited content was clobbered. Investigate before continuing.

## Flag summary

| Flag                 | Effect                                                                                       |
|----------------------|----------------------------------------------------------------------------------------------|
| (none)               | Run all pipeline steps; exit 0 on success.                                                   |
| `--with-tests`       | After the pipeline, run `pytest` (subprocess-isolated like the other steps).                 |
| `--check`            | After the pipeline (and pytest if requested), run `git status --porcelain` on the watched output paths and exit 1 if anything is modified, staged, or untracked. |

`--check` and `--with-tests` can combine. Order of post-pipeline optionals: pipeline → pytest → check. If pytest fails the driver exits before running the check; running `--check` alone afterwards still reports any drift.

## Exit codes

- `0` — every step (and any post-pipeline optionals) succeeded.
- non-zero — the first failing step's exit code. The driver prints which step failed and what to inspect.
