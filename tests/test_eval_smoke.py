"""The deterministic recorded-provider eval smoke (decisions D7, D11): zero model calls.

Replays the committed 51-prompt bundle — gpt-4.1-mini generations + Opus-authored gold judge
verdicts (D11) — and pins the frozen aggregate so a scorer/bundle regression is caught with no
inference.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from gmat_copilot.eval import run_recorded

MODEL = "openai/gpt-4.1-mini"


@pytest.mark.eval_smoke
def test_recorded_eval_is_deterministic(eval_bundle: Path) -> None:
    first = run_recorded(eval_bundle, model=MODEL)
    second = run_recorded(eval_bundle, model=MODEL)
    assert first == second  # frozen dataclasses: byte-for-byte reproducible across runs


@pytest.mark.eval_smoke
def test_recorded_eval_reproduces_the_frozen_aggregate(eval_bundle: Path) -> None:
    report = run_recorded(eval_bundle, model=MODEL)
    assert len(report.outcomes) == 51

    # The frozen v0.1 baseline: gpt-4.1-mini generation scored by structural ∧ Opus-gold judge.
    passed = [o for o in report.outcomes if o.passed]
    assert len(passed) == 41
    assert Counter(o.difficulty for o in report.outcomes) == {"easy": 20, "medium": 18, "hard": 13}
    assert Counter(o.difficulty for o in passed) == {"easy": 17, "medium": 13, "hard": 11}


@pytest.mark.eval_smoke
def test_judge_layer_catches_intent_misses(eval_bundle: Path) -> None:
    # The D6 negative control in the real frozen data: scripts that lint clean and meet every
    # structural assertion but miss the intent are failed by the judge, not the structural layer.
    report = run_recorded(eval_bundle, model=MODEL)
    judge_caught = {o.id for o in report.outcomes if o.structural.passed and not o.passed}
    assert judge_caught  # the judge layer is doing real work beyond the structural checks
    assert "lower_perigee" in judge_caught  # e.g. a wrong-direction (prograde) burn
