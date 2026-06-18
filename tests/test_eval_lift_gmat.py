"""The recorded close-the-loop verdicts checked against a *real* GMAT dry-run (decisions D12 / D13).

Marked ``gmat`` so the base matrix skips it; the gated setup-gmat job runs it. It re-runs every
recorded trajectory draft through the real gmat-run dry-run and asserts the frozen verdict (tier,
``ok``, convergence) matches reality — so the deterministic recorded lift the per-merge CI replays
is grounded in measured ground truth, not authored guesses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gmat_copilot.dryrun import dry_run
from gmat_copilot.repair import draft_hash

pytestmark = pytest.mark.gmat


def test_recorded_lift_verdicts_match_a_real_gmat(
    require_gmat: None, eval_lift_bundle: Path
) -> None:
    trajectory: dict[str, list[str]] = json.loads(
        (eval_lift_bundle / "trajectory.json").read_text("utf-8")
    )
    verdicts: dict[str, dict[str, Any]] = json.loads(
        (eval_lift_bundle / "verdicts.json").read_text("utf-8")
    )
    checked: set[str] = set()
    for scripts in trajectory.values():
        for script in scripts:
            digest = draft_hash(script)
            if digest in checked:
                continue
            checked.add(digest)
            recorded: dict[str, Any] = verdicts[digest]["dry_run"]
            real = dry_run(script)
            assert real.ok == recorded["ok"], (digest, real.tier, real.one_line)
            assert real.tier == recorded["tier"], (digest, real.one_line)
            assert real.converged == recorded["converged"], (digest, real.converged)
    assert checked  # the trajectories actually exercised the real dry-run
