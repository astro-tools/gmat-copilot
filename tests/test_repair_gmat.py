"""The repair loop driving a *real* gmat-run dry-run (decisions D12 / D13) — gated on ``[gmat]``.

Generation stays deterministic (a sequence provider, no live model), but the dynamic tier is the
real GMAT round-trip: attempt 0 is a lint-clean-but-load-failing draft, and the repair lands on a
runnable one. Marked ``gmat`` so the base matrix skips it; the gated setup-gmat job runs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import SequenceProvider, StubRetriever
from gmat_copilot import RepairTrace, draft

pytestmark = pytest.mark.gmat


def test_loop_drives_a_real_dry_run_to_convergence(
    require_gmat: None, dryrun_data: Path, valid_script: str
) -> None:
    bad = (dryrun_data / "bad_eccentricity.script").read_text(encoding="utf-8")
    provider = SequenceProvider([bad, valid_script])
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=provider,
        retriever=StubRetriever(),
        repair=1,
        dry_run=True,
    )
    # The first lint-clean draft failed GMAT's loader; the repair produced a runnable one.
    assert result.script == valid_script
    assert result.dry_run is not None and result.dry_run.ok
    trace = result.provenance
    assert isinstance(trace, RepairTrace)
    assert trace.stop_reason == "clean"
    assert len(trace.attempts) == 2
    first = trace.attempts[0]
    assert first.passed is False
    assert first.feedback_tier == "load"
    assert first.dry_run is not None and not first.dry_run.ok
    assert first.feedback  # the distilled load-tier line was fed into the repair prompt
