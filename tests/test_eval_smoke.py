"""The deterministic recorded-provider eval-smoke (decision D7): zero model calls, reproducible."""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_copilot.eval import run_recorded

MODEL = "openai/gpt-4.1-mini"


@pytest.mark.eval_smoke
def test_recorded_eval_is_deterministic_and_passes(eval_bundle: Path) -> None:
    first = run_recorded(eval_bundle, model=MODEL)
    second = run_recorded(eval_bundle, model=MODEL)

    assert first == second  # frozen dataclasses: byte-for-byte reproducible across runs
    assert len(first.outcomes) == 1
    assert first.pass_rate == 1.0

    outcome = first.outcomes[0]
    assert outcome.id == "leo_circular"
    assert outcome.structural.passed
    assert outcome.structural.failures == ()
    assert outcome.judge is True
    assert outcome.passed
