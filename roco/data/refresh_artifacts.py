"""One-command pak artifact refresh pipeline.

Chains five canonical steps in order, each as an isolated subprocess so a
failure in one cannot corrupt the next:

    1. roco.data.parse_pak           -> _data/canonical/*.jsonl
    2. roco.compiler.gen_prefix_map  -> roco/generated/handler_*, pak_ops,
                                        type_chart, weather, counter, etc.
    3. roco.data.build_db            -> _db/data.db + roco/generated/catalog_hot.py
                                        + catalog_debug.py   (catalog is written here)
    4. roco.compiler.build_effect_families
                                     -> roco/compiler/rules/effect_families.jsonl
                                        + _docs/effect_family_audit.md
    5. roco.compiler.build_effect_families --check
                                     -> stability self-check on step 4

Three optional flags layer on top:

    --skip-parse-pak   skip step 1 when only rules/codegen changed
    --with-tests       run pytest after the pipeline
    --check            after the pipeline (and pytest if requested),
                       run `git status --porcelain` over a fixed set of
                       output paths and exit 1 if anything moved.
                       This is a clean-tree / CI cleanliness probe; for
                       a real pak refresh, run without --check and
                       review the diff manually before committing.

See ``_docs/pak_refresh_pipeline.md`` for the full per-path diff contract.
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
#   - ``roco/compiler/rules/``  contains hand-edited jsonl files
#                               (exact_effects, prefix_handlers,
#                               ability_flags_from_effects, buff_immunity,
#                               effect_gap_acknowledgements) — only the
#                               generated ``effect_families.jsonl`` is in scope.
CHECK_PATHS: tuple[str, ...] = (
    "_data/canonical",
    "roco/generated",
    "roco/compiler/rules/effect_families.jsonl",
    "_docs/effect_family_audit.md",
)


def _run_step(cmd: list[str], *, label: str) -> int:
    """Run a pipeline step.  Returns the subprocess exit code.

    Tests monkeypatch this with a recorder; production calls subprocess.
    """
    print(f"[refresh] {label}")
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
    print("[refresh] check artifacts clean")
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
    if not args.skip_parse_pak:
        steps.append(("parse_pak", [py, "-m", "roco.data.parse_pak"]))
    steps.append(("gen_prefix_map", [py, "-m", "roco.compiler.gen_prefix_map"]))
    steps.append(("build_db", [py, "-m", "roco.data.build_db"]))
    steps.append(("build_effect_families", [py, "-m", "roco.compiler.build_effect_families"]))
    steps.append((
        "build_effect_families --check",
        [py, "-m", "roco.compiler.build_effect_families", "--check"],
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
    parser.add_argument(
        "--skip-parse-pak",
        action="store_true",
        help="skip parse_pak (use when rules/codegen changed but pak is unchanged)",
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
