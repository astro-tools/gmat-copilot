"""The eval runner — the recorded replay path and the live path (decisions D6, D7).

Three entry points:

- :func:`run_recorded` replays a recorded *bundle* — prompt set, recorded provider completions, and
  recorded judge verdicts — with **zero model calls and zero quota**. This is the per-merge CI path
  (D7): the structural layer re-runs live (free, deterministic) and the judge layer replays the
  frozen verdicts, so the whole eval is reproducible.
- :func:`run_live` generates a fresh draft per prompt and judges it live — the ``workflow_dispatch``
  full-suite run and the local development loop. It needs a provider credential.
- :func:`record_bundle` runs the live path once and freezes it into the two fixture files the
  recorded path replays, reproducing the same scores deterministically thereafter.

A bundle directory contains:

- ``prompts.json``     — the prompt set (see :func:`gmat_copilot.eval.prompts.load_prompts`).
- ``completions.json`` — recorded provider completions, keyed for :class:`RecordedProvider`.
- ``judge.json``       — recorded judge verdicts, ``{model: {prompt_id: [verdict, ...]}}``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..providers import Provider, RecordedProvider, prompt_key
from .judge import JUDGE_MODEL, judge_verdicts, majority
from .prompts import EvalPrompt, load_prompts
from .scorer import StructuralResult, structural_score

if TYPE_CHECKING:
    from ..rag import Retriever

__all__ = ["EvalReport", "PromptOutcome", "record_bundle", "run_live", "run_recorded"]


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    """The scored outcome for one prompt: structural, judge, and combined verdicts."""

    id: str
    difficulty: str
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

    @property
    def pass_rate_by_tier(self) -> dict[str, float]:
        """The pass-rate within each difficulty tier (decision D6 aggregates per tier)."""
        tiers: dict[str, list[bool]] = {}
        for outcome in self.outcomes:
            tiers.setdefault(outcome.difficulty, []).append(outcome.passed)
        return {tier: sum(passed) / len(passed) for tier, passed in tiers.items()}


def run_recorded(bundle_dir: str | Path, *, model: str) -> EvalReport:
    """Replay the recorded eval *bundle* for *model* and return its :class:`EvalReport`.

    Deterministic and quota-free: the structural layer re-scores the recorded completion text and
    the judge layer replays the recorded verdicts (decision D7).
    """
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
        outcomes.append(
            PromptOutcome(
                id=prompt.id,
                difficulty=prompt.difficulty,
                structural=structural,
                judge=verdict,
                passed=structural.passed and bool(verdict),
            )
        )
    return EvalReport(outcomes=tuple(outcomes))


@dataclass(frozen=True, slots=True)
class _LiveStep:
    """One prompt's live result: its outcome plus the artefacts a recording freezes."""

    outcome: PromptOutcome
    completion_key: str
    completion_entry: dict[str, Any]
    verdicts: list[bool | None]


def _evaluate_live(
    prompt: EvalPrompt,
    *,
    model: str,
    judge_model: str,
    n: int,
    provider: Provider | None,
    retriever: Retriever | None,
    judge_provider: Provider | None,
    pace: float,
) -> _LiveStep:
    """Draft a script for *prompt*, judge it live, and score it (the shared live step)."""
    from ..generate import (
        draft,  # local import keeps the recorded path free of the rag/generate deps
    )

    result = draft(
        prompt.request,
        model=model,
        strict=False,
        retriever=retriever,
        provider=provider,
    )
    structural = structural_score(result.script, prompt.structural)
    verdicts = judge_verdicts(
        prompt.intent, result.script, model=judge_model, n=n, provider=judge_provider, pace=pace
    )
    verdict = majority(verdicts)
    outcome = PromptOutcome(
        id=prompt.id,
        difficulty=prompt.difficulty,
        structural=structural,
        judge=verdict,
        passed=structural.passed and bool(verdict),
    )
    return _LiveStep(
        outcome=outcome,
        completion_key=prompt_key(result.provider, result.model, prompt.request),
        completion_entry={"text": result.script, "usage": dict(result.usage)},
        verdicts=verdicts,
    )


def run_live(
    prompts: Sequence[EvalPrompt],
    *,
    model: str,
    judge_model: str = JUDGE_MODEL,
    n: int = 3,
    provider: Provider | None = None,
    retriever: Retriever | None = None,
    judge_provider: Provider | None = None,
    pace: float = 0.0,
) -> EvalReport:
    """Generate and judge each prompt live, returning the :class:`EvalReport` (decision D6).

    Needs a reachable generation provider (*model* is a ``"provider:model"`` selector unless
    *provider* is given) and a reachable judge. *pace* seconds are slept between model calls to
    respect the free-tier per-minute budget. No fixtures are written — use :func:`record_bundle`
    to freeze a run.
    """
    outcomes: list[PromptOutcome] = []
    for index, prompt in enumerate(prompts):
        if pace and index:
            time.sleep(pace)
        step = _evaluate_live(
            prompt,
            model=model,
            judge_model=judge_model,
            n=n,
            provider=provider,
            retriever=retriever,
            judge_provider=judge_provider,
            pace=pace,
        )
        outcomes.append(step.outcome)
    return EvalReport(outcomes=tuple(outcomes))


def record_bundle(
    prompts: Sequence[EvalPrompt],
    bundle_dir: str | Path,
    *,
    model: str,
    judge_model: str = JUDGE_MODEL,
    n: int = 3,
    provider: Provider | None = None,
    retriever: Retriever | None = None,
    judge_provider: Provider | None = None,
    pace: float = 0.0,
) -> EvalReport:
    """Run the live eval once and freeze it as a recorded bundle in *bundle_dir* (decision D7).

    Writes ``completions.json`` (the generated scripts, keyed for :class:`RecordedProvider`) and
    ``judge.json`` (the raw per-run judge verdicts). ``prompts.json`` is the authored source of
    truth and is left untouched; :func:`run_recorded` on the same directory then reproduces this
    run's scores deterministically. Returns the live :class:`EvalReport`.
    """
    bundle = Path(bundle_dir)
    bundle.mkdir(parents=True, exist_ok=True)
    completions: dict[str, dict[str, Any]] = {}
    verdicts_by_prompt: dict[str, list[bool | None]] = {}
    outcomes: list[PromptOutcome] = []
    for index, prompt in enumerate(prompts):
        if pace and index:
            time.sleep(pace)
        step = _evaluate_live(
            prompt,
            model=model,
            judge_model=judge_model,
            n=n,
            provider=provider,
            retriever=retriever,
            judge_provider=judge_provider,
            pace=pace,
        )
        completions[step.completion_key] = step.completion_entry
        verdicts_by_prompt[prompt.id] = step.verdicts
        outcomes.append(step.outcome)

    _write_json(bundle / "completions.json", completions)
    _write_json(bundle / "judge.json", {judge_model: verdicts_by_prompt})
    return EvalReport(outcomes=tuple(outcomes))


def _write_json(path: Path, payload: Any) -> None:
    """Write *payload* as sorted, indented JSON with a trailing newline (stable diffs)."""
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
