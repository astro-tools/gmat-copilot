"""The close-the-loop eval: dry-run agreement + repair-loop lift (decisions D12 / D13).

The recorded path drives the *real* repair loop deterministically — a trajectory provider, an empty
retriever, recorded dry-run + judge verdicts — so no test here touches a model, the FAISS index, or
GMAT. The live path is exercised with injected stub providers and a faked dry-run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import gmat_copilot.repair as repair_mod
from conftest import SequenceProvider, StubRetriever
from gmat_copilot import draft
from gmat_copilot.eval import DraftScore, LiftReport, LiftRow, RecordedDryRun, run_recorded_lift
from gmat_copilot.eval.lift import (
    _default_retriever,
    _dry_report,
    _empty_retriever,
    _TrajectoryProvider,
    run_live_lift,
)
from gmat_copilot.eval.scorer import StructuralResult
from gmat_copilot.providers import Completion
from gmat_copilot.repair import draft_hash, evaluate
from gmat_copilot.result import DryRunReport


def _ok(tier: str = "load") -> DryRunReport:
    return DryRunReport(tier=tier, ok=True, converged=None, one_line="", raw_log="")


def _fail(tier: str = "load", one_line: str = "boom") -> DryRunReport:
    return DryRunReport(tier=tier, ok=False, converged=None, one_line=one_line, raw_log="")


# --------------------------------------------------------------------------- the small pieces


def test_recorded_dry_run_replays_by_hash() -> None:
    report = _ok()
    fn = RecordedDryRun({draft_hash("script-a"): report})
    assert fn("script-a") is report
    with pytest.raises(KeyError):
        fn("never recorded")


def test_dry_report_coerces_converged_and_defaults() -> None:
    full = _dry_report({"tier": "run", "ok": False, "converged": {"DC": False}, "one_line": "x"})
    assert full.tier == "run" and full.ok is False and full.converged == {"DC": False}
    bare = _dry_report({})  # missing keys default, a non-dict converged becomes None
    assert bare.tier == "run" and bare.ok is False and bare.converged is None


def test_trajectory_provider_yields_then_clamps() -> None:
    provider = _TrajectoryProvider(["one", "two"])
    assert [provider.complete("p", model="m").text for _ in range(3)] == ["one", "two", "two"]
    assert provider.reachable() is True


def test_empty_retriever_grounds_nothing() -> None:
    assert _empty_retriever().retrieve("anything").chunks == ()


# --------------------------------------------------------------------------- the scoring types


def _passing_structural() -> StructuralResult:
    return StructuralResult(passed=True)


def test_draft_score_static_pass_and_runnable() -> None:
    runnable = DraftScore(_passing_structural(), judge=True, dry_run_ok=True)
    assert runnable.static_pass and runnable.runnable
    # static-accepted but the dry-run rejects it -> the agreement gap, not runnable
    gap = DraftScore(_passing_structural(), judge=True, dry_run_ok=False)
    assert gap.static_pass and not gap.runnable
    # the judge rejects the intent -> not even static-accepted
    intent_miss = DraftScore(_passing_structural(), judge=False, dry_run_ok=True)
    assert not intent_miss.static_pass and not intent_miss.runnable
    # lint blocked before the dry-run -> dry_run_ok is None
    lint_block = DraftScore(StructuralResult(passed=False, failures=("lint:x",)), None, None)
    assert not lint_block.static_pass and not lint_block.runnable


def _row(difficulty: str, base: DraftScore, repaired: DraftScore) -> LiftRow:
    return LiftRow(
        id=f"{difficulty}-p",
        difficulty=difficulty,
        base=base,
        repaired=repaired,
        retries=1,
        stop_reason="clean",
    )


def test_lift_report_aggregates_per_tier() -> None:
    report = LiftReport(
        rows=(
            # easy: already runnable -> 0 lift, agreement defined and met
            _row(
                "easy",
                DraftScore(_passing_structural(), True, True),
                DraftScore(_passing_structural(), True, True),
            ),
            # medium: static-accepted but base fails dry-run; repair fixes it -> +1 lift, 0 agree
            _row(
                "medium",
                DraftScore(_passing_structural(), True, False),
                DraftScore(_passing_structural(), True, True),
            ),
            # hard: a tier whose only base draft the judge rejects -> agreement undefined (None)
            _row(
                "hard",
                DraftScore(_passing_structural(), False, True),
                DraftScore(_passing_structural(), False, True),
            ),
        ),
        budget=2,
    )
    assert report.base_runnable_by_tier == {"easy": 1.0, "medium": 0.0, "hard": 0.0}
    assert report.repaired_runnable_by_tier == {"easy": 1.0, "medium": 1.0, "hard": 0.0}
    assert report.lift_by_tier == {"easy": 0.0, "medium": 1.0, "hard": 0.0}
    assert report.dry_run_agreement_by_tier == {"easy": 1.0, "medium": 0.0, "hard": None}
    assert report.base_runnable == pytest.approx(1 / 3)
    assert report.repaired_runnable == pytest.approx(2 / 3)
    assert report.lift == pytest.approx(1 / 3)


def test_empty_lift_report() -> None:
    report = LiftReport()
    assert report.base_runnable == 0.0 and report.repaired_runnable == 0.0 and report.lift == 0.0
    assert report.lift_by_tier == {} and report.dry_run_agreement_by_tier == {}
    assert report.budget == 2


# --------------------------------------------------------------------------- the recorded path


def test_run_recorded_lift_reproduces_the_frozen_numbers(eval_lift_bundle: Path) -> None:
    report = run_recorded_lift(eval_lift_bundle)
    assert report.budget == 2
    assert {r.id for r in report.rows} == {
        "circular_leo",
        "point_mass_propagation",
        "raise_apogee_target",
        "persistent_target",
    }
    assert report.base_runnable_by_tier == {"easy": 1.0, "medium": 0.0, "hard": 0.0}
    assert report.repaired_runnable_by_tier == {"easy": 1.0, "medium": 1.0, "hard": 0.5}
    assert report.lift_by_tier == {"easy": 0.0, "medium": 1.0, "hard": 0.5}
    assert report.dry_run_agreement_by_tier == {"easy": 1.0, "medium": 0.0, "hard": 0.0}
    assert report.base_runnable == 0.25
    assert report.repaired_runnable == 0.75


def test_run_recorded_lift_is_deterministic(eval_lift_bundle: Path) -> None:
    assert run_recorded_lift(eval_lift_bundle) == run_recorded_lift(eval_lift_bundle)


def test_run_recorded_lift_traces_stop_reasons(eval_lift_bundle: Path) -> None:
    rows = {r.id: r for r in run_recorded_lift(eval_lift_bundle).rows}
    # the load-tier gap is repaired in one retry; the persistent target re-emits an identical draft
    assert rows["point_mass_propagation"].stop_reason == "clean"
    assert rows["point_mass_propagation"].retries == 1
    assert rows["persistent_target"].stop_reason == "no-progress"
    assert not rows["persistent_target"].repaired.runnable
    assert rows["circular_leo"].retries == 0  # the runnable control never fired the loop


def test_run_recorded_lift_budget_zero_is_the_single_pass(eval_lift_bundle: Path) -> None:
    # At budget 0 the loop never repairs, so base == repaired and there is no lift.
    report = run_recorded_lift(eval_lift_bundle, budget=0)
    assert all(r.retries == 0 for r in report.rows)
    assert report.lift == 0.0
    assert report.repaired_runnable == report.base_runnable == 0.25


# --------------------------------------------------------------------------- the injection seam


def test_evaluate_uses_the_injected_dry_run_fn(valid_script: str) -> None:
    calls: list[str] = []

    def fake(script: str) -> DryRunReport:
        calls.append(script)
        return _fail("run", "did not converge")

    verdict = evaluate(valid_script, dry_run=True, dry_run_fn=fake)
    assert not verdict.passed
    assert verdict.dry_run is not None and not verdict.dry_run.ok
    assert verdict.feedback == ("did not converge",) and verdict.feedback_tier == "run"
    assert calls == [valid_script]


def test_evaluate_injected_fn_is_skipped_when_lint_blocks(invalid_script: str) -> None:
    def fake(_script: str) -> DryRunReport:  # pragma: no cover - must never run
        raise AssertionError("the dry-run must not run on a lint-blocked draft")

    verdict = evaluate(invalid_script, dry_run=True, dry_run_fn=fake)
    assert not verdict.passed and verdict.feedback_tier == "lint" and verdict.dry_run is None


def test_draft_threads_the_dry_run_fn_through_the_loop(
    valid_script: str, stub_retriever: StubRetriever
) -> None:
    def fake(_script: str) -> DryRunReport:
        return _fail("load", "the ODEModel cannot be found")

    provider = SequenceProvider([valid_script])
    result = draft(
        "a LEO",
        model="m",
        provider=provider,
        retriever=stub_retriever,
        repair=0,
        dry_run=True,
        dry_run_fn=fake,
        strict=False,
    )
    assert result.dry_run is not None and not result.dry_run.ok
    assert result.dry_run.one_line == "the ODEModel cannot be found"


# --------------------------------------------------------------------------- the live path


class CannedJudge:
    """A judge provider returning a fixed verdict text for every call."""

    name = "canned"

    def __init__(self, text: str) -> None:
        self._text = text

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        return Completion(text=self._text, provider=self.name, model=model)


def test_run_live_lift_drives_the_loop_with_a_real_dry_run(
    valid_script: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The live path uses the real dry-run (dry_run_fn=None); fake it here so no GMAT is needed.
    monkeypatch.setattr(repair_mod, "_dry_run", lambda script, **kw: _ok("load"))
    from gmat_copilot.eval.prompts import EvalPrompt, StructuralSpec

    prompt = EvalPrompt(
        id="p",
        request="a LEO",
        intent="a LEO",
        structural=StructuralSpec(required_types=("Spacecraft",)),
        difficulty="easy",
    )
    report = run_live_lift(
        [prompt],
        model="m",
        provider=SequenceProvider([valid_script]),
        retriever=StubRetriever(),
        judge_provider=CannedJudge('{"satisfies_intent": true}'),
        n=1,
        budget=0,
    )
    assert len(report.rows) == 1
    assert report.rows[0].base.runnable
    assert report.lift == 0.0


def test_run_live_lift_paces_between_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(repair_mod, "_dry_run", lambda script, **kw: _ok("load"))
    from gmat_copilot.eval.prompts import EvalPrompt, StructuralSpec

    prompts = [
        EvalPrompt(
            id=f"p{i}",
            request="a LEO",
            intent="a LEO",
            structural=StructuralSpec(required_types=("Spacecraft",)),
            difficulty="easy",
        )
        for i in range(2)
    ]
    run_live_lift(
        prompts,
        model="m",
        provider=SequenceProvider(["Create Spacecraft Sat;\nBeginMissionSequence;\n"]),
        retriever=StubRetriever(),
        judge_provider=CannedJudge('{"satisfies_intent": true}'),
        n=1,
        budget=0,
        pace=1.5,
    )
    assert sleeps == [1.5]  # one sleep, before the second prompt only


def test_default_retriever_is_a_real_retriever() -> None:
    from gmat_copilot.rag import Retriever

    assert isinstance(_default_retriever(), Retriever)
