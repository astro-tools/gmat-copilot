"""The dry-run tier against a real GMAT install (decision D12) — gated on the ``[gmat]`` extra.

These exercise the tiered ``Mission.load`` / ``mission.run`` round-trip end to end through a fresh
subprocess. They are marked ``gmat`` so the GMAT-free base matrix skips them (``-m "not gmat"``);
the gated setup-gmat CI job runs them (``-m gmat``). The ``require_gmat`` fixture additionally skips
when gmat-run or a discoverable GMAT install is absent, so a local full-suite run degrades cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_copilot.dryrun import dry_run

pytestmark = pytest.mark.gmat


def _script(root: Path, name: str) -> str:
    return (root / name).read_text(encoding="utf-8")


def test_lint_clean_no_solver_loads_clean(require_gmat: None, valid_script: str) -> None:
    # A solver-free script: the config tier alone validates it; the execution tier is not entered.
    report = dry_run(valid_script)
    assert report.ok is True
    assert report.tier == "load"
    assert report.converged is None
    assert report.one_line == ""


def test_lint_clean_bad_eccentricity_caught_at_load(require_gmat: None, dryrun_data: Path) -> None:
    # ECC > 1 with a positive SMA lints clean but GMAT's loader rejects it (the dry-run-only gap).
    report = dry_run(_script(dryrun_data, "bad_eccentricity.script"))
    assert report.ok is False
    assert report.tier == "load"
    assert report.converged is None
    assert "ECC" in report.one_line
    assert "gmat-copilot-dryrun" not in report.one_line  # no temp path leaked into feedback


def test_lint_clean_bad_epoch_caught_at_load(require_gmat: None, dryrun_data: Path) -> None:
    report = dry_run(_script(dryrun_data, "bad_epoch.script"))
    assert report.ok is False
    assert report.tier == "load"
    assert "Foo" in report.one_line  # the invalid calendar month surfaces in the distilled line


def test_infeasible_target_runs_but_does_not_converge(
    require_gmat: None, dryrun_data: Path
) -> None:
    # The key "ran != solved" case: it loads and runs, yet the solver does not converge.
    report = dry_run(_script(dryrun_data, "infeasible_target.script"))
    assert report.ok is False
    assert report.tier == "run"
    assert report.converged == {"DC": False}
    assert "did not converge" in report.one_line


def test_feasible_target_converges(require_gmat: None, dryrun_data: Path) -> None:
    report = dry_run(_script(dryrun_data, "valid_target_converges.script"))
    assert report.ok is True
    assert report.tier == "run"
    assert report.converged == {"DC": True}
    assert report.one_line == ""


def test_two_dry_runs_in_one_process_isolate(
    require_gmat: None, valid_script: str, dryrun_data: Path
) -> None:
    # gmatpy cannot re-bootstrap in one interpreter; the subprocess isolation must let a second
    # dry-run run in this same process without a Moderator re-init failure.
    first = dry_run(valid_script)
    second = dry_run(_script(dryrun_data, "valid_target_converges.script"))
    assert first.ok is True
    assert second.ok is True
