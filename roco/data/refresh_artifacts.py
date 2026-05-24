"""One-command pak artifact refresh pipeline.

Chains the canonical steps in order, each as an isolated subprocess so a
failure in one cannot corrupt the next:

    1. roco.compiler_v2.gen_prefix_map  -> roco/generated/static, battle globals,
                                        skill damage adapters, handlers, etc.
    2. roco.data.build_db            -> _db/data.db + roco/generated/catalog_hot.py
                                        + catalog_debug.py   (catalog is written here)
    3. roco.compiler_v2.build_effect_families
                                     -> roco/generated/audit/effect_families.jsonl
                                        + _docs/effect_family_audit.md
    4. roco.compiler_v2.build_effect_families --check
                                     -> stability self-check on step 3
    5. roco.compiler_v2.pak_schema_audit
                                     -> _docs/pak_schema_audit.md (schema mining)
    6. roco.compiler_v2.pak_schema_audit --check
                                     -> stability self-check on step 5
    7. roco.compiler_v2.bindata_coverage_audit
                                     -> roco/generated/audit/bindata_coverage.json
    8. roco.compiler_v2.bindata_coverage_audit --check
                                     -> stability self-check on step 7

Two optional flags layer on top:

    --with-tests       run pytest after the pipeline
    --check            after the pipeline (and pytest if requested),
                       run `git status --porcelain` over a fixed set of
                       output paths and exit 1 if anything moved.
                       This is a clean-tree / CI cleanliness probe; for
                       a real pak refresh, run without --check and
                       review the diff manually before committing.

See ``README.md`` for the full pak -> generated -> DB -> engine data flow.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

# Paths the --check probe verifies for cleanliness after a refresh.
#
# Deliberately excluded:
#   - ``_db/data.db``           tracked-but-locally-modified by convention;
#                               a clean refresh always re-writes it.
CHECK_PATHS: tuple[str, ...] = (
    "roco/generated",
    "_docs/effect_family_audit.md",
    "_docs/pak_schema_audit.md",
)


def _run_step(cmd: list[str], *, label: str) -> int:
    """Run a pipeline step.  Returns the subprocess exit code.

    Tests monkeypatch this with a recorder; production calls subprocess.
    """
    print(f"[refresh] {label}", flush=True)
    return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode


def _git_status_porcelain(paths: tuple[str, ...]) -> tuple[int, str]:
    """Run ``git status --porcelain`` against ``paths``.

    Returns ``(exit_code, stdout)``.  Tests monkeypatch this with a fake
    that returns canned stdout to simulate clean / drifted trees without
    touching the real working copy.
    """
    cmd = ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", *paths]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _check_artifacts_clean() -> int:
    print("[refresh] check artifacts clean", flush=True)
    rc, out = _git_status_porcelain(CHECK_PATHS)
    if rc != 0:
        sys.stderr.write(f"[refresh] git status exited {rc}\n")
        return rc
    if out.strip():
        sys.stderr.write(
            "[refresh] tracked artifacts diverged during refresh:\n"
            f"{out}"
            f"[refresh] inspect with: git status -- {' '.join(CHECK_PATHS)}\n"
        )
        return 1
    return 0


def _build_steps(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    py = sys.executable
    steps: list[tuple[str, list[str]]] = []
    steps.append(("gen_prefix_map", [py, "-m", "roco.compiler_v2.gen_prefix_map"]))
    steps.append(("build_db", [py, "-m", "roco.data.build_db"]))
    steps.append(("build_effect_families", [py, "-m", "roco.compiler_v2.build_effect_families"]))
    steps.append((
        "build_effect_families --check",
        [py, "-m", "roco.compiler_v2.build_effect_families", "--check"],
    ))
    steps.append(("pak_schema_audit", [py, "-m", "roco.compiler_v2.pak_schema_audit"]))
    steps.append((
        "pak_schema_audit --check",
        [py, "-m", "roco.compiler_v2.pak_schema_audit", "--check"],
    ))
    steps.append(("bindata_coverage_audit", [py, "-m", "roco.compiler_v2.bindata_coverage_audit"]))
    steps.append((
        "bindata_coverage_audit --check",
        [py, "-m", "roco.compiler_v2.bindata_coverage_audit", "--check"],
    ))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-command pak artifact refresh pipeline."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="after the pipeline, run git status --porcelain over the "
             "tracked output paths and exit 1 if anything moved "
             "(clean-tree / CI cleanliness probe; not for real pak updates)",
    )
    parser.add_argument(
        "--with-tests",
        action="store_true",
        help="after the pipeline, run pytest",
    )
    args = parser.parse_args(argv)

    for label, cmd in _build_steps(args):
        rc = _run_step(cmd, label=label)
        if rc != 0:
            sys.stderr.write(f"[refresh] step {label!r} failed (exit {rc})\n")
            return rc

    if args.with_tests:
        rc = _run_step([sys.executable, "-m", "pytest"], label="pytest")
        if rc != 0:
            return rc

    if args.check:
        rc = _check_artifacts_clean()
        if rc != 0:
            return rc

    print("[refresh] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
