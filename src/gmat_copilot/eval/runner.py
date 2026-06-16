"""Deterministic recorded-eval replay — the per-merge CI path (decision D7).

Replays a recorded eval *bundle* — a prompt set, recorded provider completions, and recorded judge
verdicts — with zero model calls and zero quota. The structural layer always runs live (free,
deterministic); the judge layer replays the recorded verdicts. The live path is added by the
eval-suite work.

A bundle directory contains:

- ``prompts.json``     — the prompt set (see :func:`gmat_copilot.eval.prompts.load_prompts`).
- ``completions.json`` — recorded provider completions, keyed for :class:`RecordedProvider`.
- ``judge.json``       — recorded judge verdicts, ``{model: {prompt_id: [verdict, ...]}}``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..providers import RecordedProvider
from .judge import majority
from .prompts import load_prompts
from .scorer import StructuralResult, structural_score

__all__ = ["EvalReport", "PromptOutcome", "run_recorded"]


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    """The scored outcome for one prompt: structural, judge, and combined verdicts."""

    id: str
    structural: StructuralResult
    judge: bool | None
    passed: bool


@dataclass(frozen=True, slots=True)
class EvalReport:
    """The outcomes for an eval run and the aggregate pass-rate."""

    outcomes: tuple[PromptOutcome, ...] = ()

    @property
    def pass_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(1 for outcome in self.outcomes if outcome.passed) / len(self.outcomes)


def run_recorded(bundle_dir: str | Path, *, model: str) -> EvalReport:
    """Replay the recorded eval *bundle* for *model* and return its :class:`EvalReport`."""
    bundle = Path(bundle_dir)
    prompts = load_prompts(bundle / "prompts.json")
    completions: dict[str, Any] = json.loads((bundle / "completions.json").read_text("utf-8"))
    verdicts: dict[str, Any] = json.loads((bundle / "judge.json").read_text("utf-8"))
    per_model = verdicts.get(model, verdicts)

    provider = RecordedProvider(completions)
    outcomes: list[PromptOutcome] = []
    for prompt in prompts:
        completion = provider.complete(prompt.request, model=model)
        structural = structural_score(completion.text, prompt.structural)
        verdict = majority(per_model.get(prompt.id, []))
        passed = structural.passed and bool(verdict)
        outcomes.append(
            PromptOutcome(id=prompt.id, structural=structural, judge=verdict, passed=passed)
        )
    return EvalReport(outcomes=tuple(outcomes))
