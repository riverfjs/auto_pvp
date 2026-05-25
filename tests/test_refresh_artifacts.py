"""Unit tests for the pak refresh pipeline driver.

These tests monkeypatch the driver's own ``_run_step`` and
``_git_status_porcelain`` callables so the orchestration logic can be
verified without spawning real subprocesses or touching git.  The
    wrapped pipeline modules (gen_prefix_map, catalog_compiler,
build_effect_families) have their own dedicated tests and are not
re-exercised here.
"""

from __future__ import annotations

from typing import Any

import roco.data.refresh_artifacts as refresh


def _recorder(rc_by_label: dict[str, int] | None = None):
    rc_by_label = rc_by_label or {}
    calls: list[tuple[str, list[str]]] = []

    def fake(cmd: list[str], *, label: str) -> int:
        calls.append((label, list(cmd)))
        return rc_by_label.get(label, 0)

    return fake, calls


def _stub_clean_status(monkeypatch) -> list[tuple[str, ...]]:
    """Install a fake ``_git_status_porcelain`` that always reports clean.

    Returns the list it appends each invocation's ``paths`` argument to,
    so tests can assert what paths the driver passed in.
    """
    seen: list[tuple[str, ...]] = []

    def fake_status(paths: tuple[str, ...]) -> tuple[int, str]:
        seen.append(tuple(paths))
        return 0, ""

    monkeypatch.setattr(refresh, "_git_status_porcelain", fake_status)
    return seen


# ── pipeline ordering ─────────────────────────────────────────────────────


def test_default_order(monkeypatch):
    fake, calls = _recorder()
    monkeypatch.setattr(refresh, "_run_step", fake)
    assert refresh.main([]) == 0
    assert [label for label, _ in calls] == [
        "gen_prefix_map",
        "gen_runtime_artifacts",
        "catalog_compiler",
        "build_effect_families",
        "build_effect_families --check",
        "pak_schema_audit",
        "pak_schema_audit --check",
        "bindata_coverage_audit",
        "bindata_coverage_audit --check",
    ]


def test_failure_halts(monkeypatch):
    fake, calls = _recorder({"gen_prefix_map": 7})
    monkeypatch.setattr(refresh, "_run_step", fake)
    assert refresh.main([]) == 7
    assert [label for label, _ in calls] == ["gen_prefix_map"]


def test_with_tests_appends_pytest(monkeypatch):
    fake, calls = _recorder()
    monkeypatch.setattr(refresh, "_run_step", fake)
    assert refresh.main(["--with-tests"]) == 0
    assert calls[-1][0] == "pytest"


# ── --check behaviour (uses git status --porcelain) ───────────────────────


def test_check_invokes_git_status_with_paths(monkeypatch):
    fake, calls = _recorder()
    monkeypatch.setattr(refresh, "_run_step", fake)
    seen = _stub_clean_status(monkeypatch)
    assert refresh.main(["--check"]) == 0
    # _git_status_porcelain must be called exactly once with CHECK_PATHS.
    assert seen == [refresh.CHECK_PATHS]
    # _run_step should not have been used for the status invocation.
    labels = [label for label, _ in calls]
    assert "check artifacts clean" not in labels


def test_check_drift_returns_nonzero(monkeypatch):
    fake, _calls = _recorder()
    monkeypatch.setattr(refresh, "_run_step", fake)

    def drifted(paths: tuple[str, ...]) -> tuple[int, str]:
        return 0, " M roco/generated/catalog/hot.py\n"

    monkeypatch.setattr(refresh, "_git_status_porcelain", drifted)
    assert refresh.main(["--check"]) == 1


def test_check_propagates_git_failure(monkeypatch):
    fake, _calls = _recorder()
    monkeypatch.setattr(refresh, "_run_step", fake)

    def errored(paths: tuple[str, ...]) -> tuple[int, str]:
        return 128, ""

    monkeypatch.setattr(refresh, "_git_status_porcelain", errored)
    assert refresh.main(["--check"]) == 128


# ── post-pipeline optionals combine in order: pipeline → pytest → check ──


def test_with_tests_and_check_run_in_order(monkeypatch):
    fake, calls = _recorder()
    monkeypatch.setattr(refresh, "_run_step", fake)
    _stub_clean_status(monkeypatch)
    assert refresh.main(["--with-tests", "--check"]) == 0
    labels = [label for label, _ in calls]
    assert labels == [
        "gen_prefix_map",
        "gen_runtime_artifacts",
        "catalog_compiler",
        "build_effect_families",
        "build_effect_families --check",
        "pak_schema_audit",
        "pak_schema_audit --check",
        "bindata_coverage_audit",
        "bindata_coverage_audit --check",
        "pytest",
    ]


# ── CHECK_PATHS shape: generated outputs only, not hand rules ─────────────


def test_check_paths_exclude_full_rules_dir():
    # The full rules directory must NOT be in scope. Generated audits live
    # under roco/generated, so hand-edited rule files are not reported as
    # artifact drift by this probe.
    assert "roco/compiler_v2/rules" not in refresh.CHECK_PATHS
    assert "roco/compiler_v2/rules/effect_families.jsonl" not in refresh.CHECK_PATHS
    # Sanity: the other expected output scopes are present.
    assert "_data/canonical" not in refresh.CHECK_PATHS
    assert "roco/generated" in refresh.CHECK_PATHS
    assert "_docs/effect_family_audit.md" in refresh.CHECK_PATHS
    assert "_docs/pak_schema_audit.md" in refresh.CHECK_PATHS
