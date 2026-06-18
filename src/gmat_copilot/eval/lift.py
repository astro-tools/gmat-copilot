"""Close-the-loop eval: the dry-run-agreement tier and the repair-loop lift (decisions D12, D13).

Where the static eval (:mod:`gmat_copilot.eval.runner`) scores ``structural ∧ judge`` on a single
draft, this measures what v0.2's close-the-loop adds:

- **Dry-run agreement** — of the drafts the static eval accepts (``structural ∧ judge``), the
  fraction that also *run* under the gmat-run dry-run. The shortfall is the static-vs-dynamic gap
  (decisions D5 / D12): lint-clean, intent-correct scripts GMAT's loader or solver still rejects.
- **Repair-loop lift** — the close-the-loop pass-rate (``structural ∧ judge ∧ dry-run``) the bounded
  repair loop (decision D13) recovers over a single pass: the rate at the D13 budget minus the rate
  at ``repair = 0``.

Both come from a **single** ``draft(repair=budget, dry_run=True)`` call per prompt: its provenance
trace holds every attempt, so attempt 0 is the ``repair = 0`` outcome and the final attempt the
``repair = budget`` outcome — no double run.

Per decision D7 the **recorded** path replays a fixed repair trajectory plus recorded dry-run and
judge verdicts (a :class:`_TrajectoryProvider`, an empty retriever, and a :class:`RecordedDryRun`) —
zero model calls, zero GMAT — while the **live** path drives a real model and a real GMAT dry-run on
demand (the gated job / fixture refresh).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..providers import Completion, Provider
from ..repair import DryRunFn, draft_hash
from ..result import DryRunReport, RetrievalTrace
from .judge import JUDGE_MODEL, judge_verdicts, majority
from .prompts import EvalPrompt, load_prompts
from .scorer import StructuralResult, structural_score

if TYPE_CHECKING:
    from ..rag import Retriever
    from ..result import DraftAttempt

__all__ = [
    "DraftScore",
    "LiftReport",
    "LiftRow",
    "RecordedDryRun",
    "run_live_lift",
    "run_recorded_lift",
]

#: ``(prompt, script) -> verdict`` — the semantic layer, recorded or live, for a specific draft.
JudgeFn = Callable[[EvalPrompt, str], "bool | None"]

#: The D13 default retry budget — one repair does the work, a second covers prompt-distribution
#: variance; beyond that no-progress dominates (the V5 measured plateau).
DEFAULT_BUDGET = 2


@dataclass(frozen=True, slots=True)
class DraftScore:
    """One draft's close-the-loop score: the two static layers plus the dynamic dry-run verdict."""

    structural: StructuralResult
    judge: bool | None
    #: The dynamic tier: True/False when the dry-run ran, ``None`` when lint blocked before it.
    dry_run_ok: bool | None

    @property
    def static_pass(self) -> bool:
        """What the v0.1 static eval accepts: structurally clean *and* judged intent-correct."""
        return self.structural.passed and bool(self.judge)

    @property
    def runnable(self) -> bool:
        """The full close-the-loop pass: static-accepted *and* the dry-run is ``ok``."""
        return self.static_pass and bool(self.dry_run_ok)


@dataclass(frozen=True, slots=True)
class LiftRow:
    """One prompt's close-the-loop outcome at ``repair = 0`` (*base*) and the budget (*repaired*).

    *base* is the single-pass (v0.1) draft; *repaired* is the draft the bounded loop converged to.
    """

    id: str
    difficulty: str
    base: DraftScore
    repaired: DraftScore
    #: Repairs the loop spent to reach *repaired*: one fewer than the attempts recorded (D13).
    retries: int
    #: Why the loop stopped: ``"clean"`` / ``"budget"`` / ``"no-progress"`` / ``"oscillation"``.
    stop_reason: str


def _rate(flags: Sequence[bool]) -> float:
    return sum(flags) / len(flags) if flags else 0.0


@dataclass(frozen=True, slots=True)
class LiftReport:
    """The close-the-loop outcomes and the per-tier dry-run-agreement and repair-lift aggregates."""

    rows: tuple[LiftRow, ...] = ()
    budget: int = DEFAULT_BUDGET

    def _tiers(self) -> dict[str, list[LiftRow]]:
        tiers: dict[str, list[LiftRow]] = {}
        for row in self.rows:
            tiers.setdefault(row.difficulty, []).append(row)
        return tiers

    @property
    def base_runnable_by_tier(self) -> dict[str, float]:
        """The close-the-loop pass-rate per tier at ``repair = 0`` (the single-pass baseline)."""
        return {t: _rate([r.base.runnable for r in rows]) for t, rows in self._tiers().items()}

    @property
    def repaired_runnable_by_tier(self) -> dict[str, float]:
        """The close-the-loop pass-rate per tier at the repair budget."""
        return {t: _rate([r.repaired.runnable for r in rows]) for t, rows in self._tiers().items()}

    @property
    def lift_by_tier(self) -> dict[str, float]:
        """The repair-loop lift per tier: repaired pass-rate minus base pass-rate (decision D13)."""
        base, repaired = self.base_runnable_by_tier, self.repaired_runnable_by_tier
        return {t: repaired[t] - base[t] for t in base}

    @property
    def dry_run_agreement_by_tier(self) -> dict[str, float | None]:
        """Per tier, the fraction of statically-accepted base drafts that also pass the dry-run.

        The denominator is the drafts the v0.1 static eval would pass (``structural ∧ judge``) at
        ``repair = 0``; the numerator, those whose dry-run is also ``ok``. ``None`` for a tier with
        no statically-accepted draft to compare (the agreement is undefined, not 0). The shortfall
        below 1.0 is the static-vs-dynamic gap the dry-run tier exists to surface (decision D12).
        """
        out: dict[str, float | None] = {}
        for tier, rows in self._tiers().items():
            accepted = [r for r in rows if r.base.static_pass]
            out[tier] = _rate([bool(r.base.dry_run_ok) for r in accepted]) if accepted else None
        return out

    @property
    def base_runnable(self) -> float:
        """The overall close-the-loop pass-rate at ``repair = 0``."""
        return _rate([r.base.runnable for r in self.rows])

    @property
    def repaired_runnable(self) -> float:
        """The overall close-the-loop pass-rate at the repair budget."""
        return _rate([r.repaired.runnable for r in self.rows])

    @property
    def lift(self) -> float:
        """The overall repair-loop lift: repaired minus base pass-rate."""
        return self.repaired_runnable - self.base_runnable


def _dry_report(raw: Mapping[str, Any]) -> DryRunReport:
    """Build a :class:`DryRunReport` from a recorded ``dry_run`` verdict mapping."""
    converged = raw.get("converged")
    return DryRunReport(
        tier=str(raw.get("tier", "run")),
        ok=bool(raw.get("ok", False)),
        converged=dict(converged) if isinstance(converged, dict) else None,
        one_line=str(raw.get("one_line", "")),
        raw_log=str(raw.get("raw_log", "")),
    )


@dataclass(frozen=True, slots=True)
class RecordedDryRun:
    """A :data:`~gmat_copilot.repair.DryRunFn` that replays recorded verdicts keyed by draft hash.

    The deterministic, GMAT-free dynamic tier the recorded close-the-loop eval drives the real loop
    with (decision D7): :func:`gmat_copilot.draft` calls it instead of the gmat-run subprocess.
    """

    verdicts: Mapping[str, DryRunReport]

    def __call__(self, script: str) -> DryRunReport:
        report = self.verdicts.get(draft_hash(script))
        if report is None:
            raise KeyError("no recorded dry-run verdict for this draft; record it first")
        return report


class _TrajectoryProvider:
    """Replays a fixed list of draft scripts in order, ignoring the prompt (the recorded loop).

    The i-th ``complete`` returns the i-th recorded draft, clamping to the last once exhausted — so
    a re-draft of the final script models the no-progress stop, exactly like the live loop hitting a
    model that cannot improve. Reports ``provider == "recorded"``.
    """

    name = "recorded"

    def __init__(self, scripts: Sequence[str]) -> None:
        self._scripts = list(scripts)
        self._index = 0

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        script = self._scripts[min(self._index, len(self._scripts) - 1)]
        self._index += 1
        return Completion(text=script, provider=self.name, model=model)


class _EmptyRetriever:
    """A retriever that grounds nothing — keeps the recorded loop off the FAISS index / embedder."""

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        return RetrievalTrace()


def _score(attempt: DraftAttempt, prompt: EvalPrompt, judge: bool | None) -> DraftScore:
    """Score one loop attempt: re-run structural, fold in the judge and the dry-run verdict."""
    structural = structural_score(attempt.script, prompt.structural)
    dry_run_ok = attempt.dry_run.ok if attempt.dry_run is not None else None
    return DraftScore(structural=structural, judge=judge, dry_run_ok=dry_run_ok)


def _run_lift(
    prompts: Sequence[EvalPrompt],
    *,
    budget: int,
    build_provider: Callable[[EvalPrompt], Provider | None],
    retriever: Retriever | None,
    judge: JudgeFn,
    dry_run_fn: DryRunFn | None,
    model: str,
    gmat_root: str | None = None,
    pace: float = 0.0,
) -> LiftReport:
    """Drive the real repair loop once per prompt and score the base and repaired drafts.

    A single ``draft(repair=budget, dry_run=True)`` per prompt yields both budgets from its
    provenance trace (attempt 0 = base, the final attempt = repaired). The recorded and live callers
    differ only in the injected provider, retriever, judge, and dry-run.
    """
    from ..generate import draft  # local import keeps `import gmat_copilot.eval` light (cf runner)
    from ..provenance import Provenance

    rows: list[LiftRow] = []
    for index, prompt in enumerate(prompts):
        if pace and index:
            time.sleep(pace)
        result = draft(
            prompt.request,
            model=model,
            strict=False,
            provider=build_provider(prompt),
            retriever=retriever,
            repair=budget,
            dry_run=True,
            dry_run_fn=dry_run_fn,
            gmat_root=gmat_root,
        )
        prov = result.provenance
        assert isinstance(prov, Provenance)  # draft() always populates it (decision D14)
        attempts = prov.repair.attempts
        base = _score(attempts[0], prompt, judge(prompt, attempts[0].script))
        repaired = _score(attempts[-1], prompt, judge(prompt, attempts[-1].script))
        rows.append(
            LiftRow(
                id=prompt.id,
                difficulty=prompt.difficulty,
                base=base,
                repaired=repaired,
                retries=len(attempts) - 1,
                stop_reason=prov.repair.stop_reason,
            )
        )
    return LiftReport(rows=tuple(rows), budget=budget)


def run_recorded_lift(bundle_dir: str | Path, *, budget: int = DEFAULT_BUDGET) -> LiftReport:
    """Replay the recorded close-the-loop *bundle* and return its :class:`LiftReport` (decision D7).

    Deterministic and quota-free: a :class:`_TrajectoryProvider` replays each prompt's recorded
    repair trajectory through the real loop, a :class:`RecordedDryRun` replays the dynamic tier, and
    the recorded judge verdicts settle the semantic layer — zero model calls, zero GMAT.

    A bundle directory holds:

    - ``prompts.json``    — the prompt set (see :func:`gmat_copilot.eval.prompts.load_prompts`).
    - ``trajectory.json`` — ``{prompt_id: [draft_script, ...]}``, the recorded repair sequence.
    - ``verdicts.json``   — ``{draft_hash: {"dry_run": {...}, "judge": [verdict, ...]}}``.
    """
    bundle = Path(bundle_dir)
    prompts = load_prompts(bundle / "prompts.json")
    trajectory: dict[str, list[str]] = json.loads((bundle / "trajectory.json").read_text("utf-8"))
    raw_verdicts: dict[str, Any] = json.loads((bundle / "verdicts.json").read_text("utf-8"))
    dry_run_fn = RecordedDryRun(
        {h: _dry_report(v.get("dry_run", {})) for h, v in raw_verdicts.items()}
    )
    judge_by_hash = {h: majority(v.get("judge", [])) for h, v in raw_verdicts.items()}

    def judge(_prompt: EvalPrompt, script: str) -> bool | None:
        return judge_by_hash.get(draft_hash(script))

    return _run_lift(
        prompts,
        budget=budget,
        build_provider=lambda prompt: _TrajectoryProvider(trajectory[prompt.id]),
        retriever=_empty_retriever(),
        judge=judge,
        dry_run_fn=dry_run_fn,
        model="recorded",
    )


def run_live_lift(
    prompts: Sequence[EvalPrompt],
    *,
    model: str,
    judge_model: str = JUDGE_MODEL,
    n: int = 3,
    budget: int = DEFAULT_BUDGET,
    provider: Provider | None = None,
    retriever: Retriever | None = None,
    judge_provider: Provider | None = None,
    gmat_root: str | None = None,
    pace: float = 0.0,
) -> LiftReport:
    """Run the close-the-loop eval live: a real model, a real GMAT dry-run, and a live judge.

    The on-demand / fixture-refresh path (decision D7) — needs a reachable generation provider, the
    ``[gmat]`` extra with a GMAT install, and a reachable judge. *pace* seconds are slept between
    prompts to respect the free-tier daily budget. No fixtures are written.
    """
    retriever = retriever if retriever is not None else _default_retriever()

    def judge(prompt: EvalPrompt, script: str) -> bool | None:
        return majority(
            judge_verdicts(
                prompt.intent, script, model=judge_model, n=n, provider=judge_provider, pace=pace
            )
        )

    return _run_lift(
        prompts,
        budget=budget,
        build_provider=lambda _prompt: provider,
        retriever=retriever,
        judge=judge,
        dry_run_fn=None,  # the real gmat-run dry-run (decision D12)
        model=model,
        gmat_root=gmat_root,
        pace=pace,
    )


def _empty_retriever() -> Retriever:
    """An empty-grounding retriever, typed as :class:`~gmat_copilot.rag.Retriever` for the loop."""
    from typing import cast

    return cast("Retriever", _EmptyRetriever())


def _default_retriever() -> Retriever:
    """A real corpus retriever, built once and reused across the live run's prompts."""
    from ..rag import Retriever

    return Retriever()
