"""The bounded repair loop (decision D13): convergence, stop conditions, and draft() integration.

GMAT-free throughout: generation is driven by a deterministic sequence provider, and the dynamic
dry-run tier is monkeypatched where exercised. The real-GMAT loop end-to-end lives in
``test_repair_gmat.py`` under the gated CI job.
"""

from __future__ import annotations

import pytest

from conftest import SequenceProvider, StubRetriever
from gmat_copilot import CopilotResult, DraftRejected, Provenance, draft
from gmat_copilot import repair as repair_mod
from gmat_copilot.repair import aggregate_usage, build_repair_prompt, draft_hash, evaluate
from gmat_copilot.result import DraftAttempt, DryRunReport, LintReport, RepairTrace

# Two distinct lint-failing drafts and a third, for oscillation / budget tests.
_BAD_A = "@@@ bad draft A @@@"
_BAD_B = "### bad draft B ###"
_BAD_C = "&&& bad draft C &&&"


def _repair_trace(result: CopilotResult) -> RepairTrace:
    """The D13 repair trace nested in a result's D14 provenance record."""
    prov = result.provenance
    assert isinstance(prov, Provenance)
    return prov.repair


# --------------------------------------------------------------------------- evaluate (lint-first)


def test_evaluate_reports_lint_failure_as_the_lint_tier(invalid_script: str) -> None:
    verdict = evaluate(invalid_script, dry_run=False)
    assert verdict.passed is False
    assert verdict.feedback_tier == "lint"
    assert verdict.feedback  # the blocking diagnostics, as feedback lines
    assert verdict.dry_run is None


def test_evaluate_clean_script_passes_without_the_dynamic_tier(valid_script: str) -> None:
    verdict = evaluate(valid_script, dry_run=False)
    assert verdict.passed is True
    assert verdict.feedback == ()
    assert verdict.dry_run is None


def test_evaluate_runs_dry_run_only_when_clean_and_enabled(
    monkeypatch: pytest.MonkeyPatch, valid_script: str, invalid_script: str
) -> None:
    calls: list[str] = []

    def fake(script: str, *, gmat_root: str | None = None, timeout: float = 300.0) -> DryRunReport:
        calls.append(script)
        return DryRunReport(tier="load", ok=True, converged=None, one_line="", raw_log="")

    monkeypatch.setattr(repair_mod, "_dry_run", fake)

    evaluate(invalid_script, dry_run=True)  # lint fails first — the dynamic tier is never reached
    assert calls == []

    verdict = evaluate(valid_script, dry_run=True)  # lint-clean — the dynamic tier runs
    assert calls == [valid_script]
    assert verdict.passed is True
    assert verdict.dry_run is not None and verdict.dry_run.ok


def test_evaluate_surfaces_the_dry_run_one_line_on_failure(
    monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    def fake(script: str, *, gmat_root: str | None = None, timeout: float = 300.0) -> DryRunReport:
        return DryRunReport(
            tier="run",
            ok=False,
            converged={"DC": False},
            one_line="solver(s) DC did not converge",
            raw_log="log",
        )

    monkeypatch.setattr(repair_mod, "_dry_run", fake)
    verdict = evaluate(valid_script, dry_run=True)
    assert verdict.passed is False
    assert verdict.feedback == ("solver(s) DC did not converge",)
    assert verdict.feedback_tier == "run"


def test_evaluate_falls_back_when_the_dry_run_gives_no_one_line(
    monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    # A failed dry-run with an empty one-line (e.g. a crash) still yields actionable feedback.
    def fake(script: str, *, gmat_root: str | None = None, timeout: float = 300.0) -> DryRunReport:
        return DryRunReport(tier="crash", ok=False, converged=None, one_line="", raw_log="")

    monkeypatch.setattr(repair_mod, "_dry_run", fake)
    verdict = evaluate(valid_script, dry_run=True)
    assert verdict.passed is False
    assert verdict.feedback == ("the dry-run failed",)
    assert verdict.feedback_tier == "crash"


# --------------------------------------------------------------------------- helpers


def test_build_repair_prompt_carries_request_draft_and_feedback() -> None:
    prompt = build_repair_prompt("make a 500 km LEO", "BAD SCRIPT", ("error: x", "error: y"))
    assert "make a 500 km LEO" in prompt
    assert "BAD SCRIPT" in prompt
    assert "- error: x" in prompt
    assert "- error: y" in prompt
    assert "Problems to fix" in prompt


def test_aggregate_usage_sums_per_key() -> None:
    first = DraftAttempt("s", LintReport(), None, True, (), None, {"in": 1, "out": 2})
    second = DraftAttempt("s", LintReport(), None, True, (), None, {"in": 3})
    assert aggregate_usage((first, second)) == {"in": 4, "out": 2}


def test_draft_hash_is_stable_and_distinct() -> None:
    assert draft_hash("x") == draft_hash("x")
    assert draft_hash("x") != draft_hash("y")


# --------------------------------------------------------------------------- draft() — single pass


def test_repair_zero_is_a_single_pass(valid_script: str, stub_retriever: StubRetriever) -> None:
    provider = SequenceProvider([valid_script])
    result = draft("a LEO", model="m", provider=provider, retriever=stub_retriever, repair=0)
    assert result.script == valid_script
    assert result.lint.clean
    assert result.dry_run is None
    assert result.usage == {"total_tokens": 1}  # the single completion's usage, unchanged
    assert len(provider.prompts) == 1  # exactly one generation, no regeneration
    trace = _repair_trace(result)
    assert trace.stop_reason == "clean"
    assert len(trace.attempts) == 1


def test_repair_zero_strict_raises_after_one_attempt(
    invalid_script: str, stub_retriever: StubRetriever
) -> None:
    provider = SequenceProvider([invalid_script])
    with pytest.raises(DraftRejected) as excinfo:
        draft("broken", model="m", provider=provider, retriever=stub_retriever, repair=0)
    assert len(provider.prompts) == 1  # budget 0 never regenerates
    rejected = excinfo.value.result
    assert rejected.script == invalid_script
    trace = _repair_trace(rejected)
    assert trace.stop_reason == "budget"


# --------------------------------------------------------------------------- draft() — repair loop


def test_repair_converges_bad_then_good(
    invalid_script: str, valid_script: str, stub_retriever: StubRetriever
) -> None:
    provider = SequenceProvider([invalid_script, valid_script])
    result = draft("a LEO", model="m", provider=provider, retriever=stub_retriever, repair=2)
    assert result.script == valid_script
    assert result.lint.clean
    assert len(provider.prompts) == 2  # fixed on the first repair; budget not exhausted
    # The repair prompt carried the failing draft and its diagnostics.
    assert invalid_script in provider.prompts[1]
    assert "Problems to fix" in provider.prompts[1]
    trace = _repair_trace(result)
    assert trace.stop_reason == "clean"
    assert len(trace.attempts) == 2
    assert trace.attempts[0].feedback_tier == "lint"
    assert trace.attempts[0].passed is False
    assert trace.attempts[1].passed is True


def test_repair_stops_on_no_progress(invalid_script: str, stub_retriever: StubRetriever) -> None:
    # The provider re-emits the identical broken draft: the loop must stop, not spend the budget.
    provider = SequenceProvider([invalid_script])  # clamps -> same script every call
    with pytest.raises(DraftRejected) as excinfo:
        draft("broken", model="m", provider=provider, retriever=stub_retriever, repair=5)
    assert len(provider.prompts) == 2  # attempt 0 + one identical re-draft
    trace = _repair_trace(excinfo.value.result)
    assert trace.stop_reason == "no-progress"


def test_repair_stops_on_oscillation(stub_retriever: StubRetriever) -> None:
    # A, B, then A again — a defect reintroduced — stops as oscillation.
    provider = SequenceProvider([_BAD_A, _BAD_B, _BAD_A, _BAD_B])
    with pytest.raises(DraftRejected) as excinfo:
        draft("broken", model="m", provider=provider, retriever=stub_retriever, repair=5)
    assert len(provider.prompts) == 3  # A, B, A(=oscillation)
    trace = _repair_trace(excinfo.value.result)
    assert trace.stop_reason == "oscillation"


def test_repair_exhausts_the_budget_on_persistent_distinct_failures(
    stub_retriever: StubRetriever,
) -> None:
    provider = SequenceProvider([_BAD_A, _BAD_B, _BAD_C])
    with pytest.raises(DraftRejected) as excinfo:
        draft("broken", model="m", provider=provider, retriever=stub_retriever, repair=2)
    assert len(provider.prompts) == 3  # attempts 0, 1, 2 — all distinct failures
    trace = _repair_trace(excinfo.value.result)
    assert trace.stop_reason == "budget"
    assert len(trace.attempts) == 3


def test_permissive_returns_the_final_draft_with_diagnostics(
    stub_retriever: StubRetriever,
) -> None:
    provider = SequenceProvider([_BAD_A, _BAD_B])
    result = draft(
        "broken", model="m", strict=False, provider=provider, retriever=stub_retriever, repair=1
    )
    assert result.script == _BAD_B  # the final draft, returned not raised
    assert not result.lint.clean
    trace = _repair_trace(result)
    assert trace.stop_reason == "budget"


def test_usage_aggregates_across_attempts(
    invalid_script: str, valid_script: str, stub_retriever: StubRetriever
) -> None:
    provider = SequenceProvider([invalid_script, valid_script], usage={"total_tokens": 5})
    result = draft("a LEO", model="m", provider=provider, retriever=stub_retriever, repair=1)
    assert result.usage == {"total_tokens": 10}  # two attempts of 5


def test_negative_repair_budget_is_rejected(
    valid_script: str, stub_retriever: StubRetriever
) -> None:
    with pytest.raises(ValueError, match="repair budget"):
        draft(
            "a LEO",
            model="m",
            provider=SequenceProvider([valid_script]),
            retriever=stub_retriever,
            repair=-1,
        )


def test_loop_repairs_on_dry_run_feedback(
    monkeypatch: pytest.MonkeyPatch, valid_script: str, stub_retriever: StubRetriever
) -> None:
    # Both drafts lint clean; the dynamic tier fails the first and passes the second, so the loop
    # repairs on the dry-run one-line — the lint-clean-but-unrunnable case the loop exists for.
    calls: list[str] = []

    def fake(script: str, *, gmat_root: str | None = None, timeout: float = 300.0) -> DryRunReport:
        calls.append(script)
        if len(calls) == 1:
            return DryRunReport(
                tier="load", ok=False, converged=None, one_line="bad eccentricity", raw_log="log"
            )
        return DryRunReport(tier="load", ok=True, converged=None, one_line="", raw_log="")

    monkeypatch.setattr(repair_mod, "_dry_run", fake)
    second = valid_script + "\n% revised\n"
    provider = SequenceProvider([valid_script, second])
    result = draft(
        "a LEO", model="m", provider=provider, retriever=stub_retriever, repair=1, dry_run=True
    )
    assert result.script == second
    assert result.dry_run is not None and result.dry_run.ok
    assert "bad eccentricity" in provider.prompts[1]  # the dry-run one-line was fed back
    trace = _repair_trace(result)
    assert trace.stop_reason == "clean"
    assert trace.attempts[0].feedback_tier == "load"
    assert trace.attempts[0].dry_run is not None and not trace.attempts[0].dry_run.ok


def test_strict_raises_on_a_persistent_dry_run_failure(
    monkeypatch: pytest.MonkeyPatch, valid_script: str, stub_retriever: StubRetriever
) -> None:
    def fake(script: str, *, gmat_root: str | None = None, timeout: float = 300.0) -> DryRunReport:
        return DryRunReport(
            tier="run",
            ok=False,
            converged={"DC": False},
            one_line="solver(s) DC did not converge",
            raw_log="log",
        )

    monkeypatch.setattr(repair_mod, "_dry_run", fake)
    # Distinct lint-clean drafts so the loop spends the budget rather than stopping on no-progress.
    provider = SequenceProvider([valid_script, valid_script + "\n% v2\n"])
    with pytest.raises(DraftRejected, match="did not converge") as excinfo:
        draft(
            "a LEO", model="m", provider=provider, retriever=stub_retriever, repair=1, dry_run=True
        )
    result = excinfo.value.result
    assert result.dry_run is not None and not result.dry_run.ok
