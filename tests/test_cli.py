"""The ``gmat-copilot`` CLI plumbing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from gmat_copilot import DryRunReport, Outcome, Provenance
from gmat_copilot.cli import _lint_summary, main
from gmat_copilot.eval.runner import EvalReport, PromptOutcome
from gmat_copilot.eval.scorer import StructuralResult
from gmat_copilot.generate import _compose_prompt, draft
from gmat_copilot.providers import RecordedProvider, prompt_key
from gmat_copilot.rag import Retriever
from gmat_copilot.result import (
    CopilotResult,
    DraftAttempt,
    LintDiagnostic,
    LintReport,
    RepairTrace,
    RetrievalTrace,
    Severity,
)


class _OfflineRetriever(Retriever):
    """A retriever stand-in that returns an empty trace without loading the embedding model.

    ``draft()`` retrieves before it calls the provider, so a CLI test that reaches the provider
    would otherwise download the real embedder. This keeps the test hermetic. It doubles as both a
    ``retriever=`` instance and a drop-in for ``gmat_copilot.generate.Retriever``.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__()

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        return RetrievalTrace()


def _install_recorded(
    monkeypatch: pytest.MonkeyPatch, request: str, model: str, completion_text: str
) -> RecordedProvider:
    """Wire ``draft()`` (as the CLI calls it) onto a deterministic recorded provider.

    Patches ``select`` to hand back a :class:`RecordedProvider` keyed on the exact prompt ``draft``
    composes for *request* under an empty retrieval, and ``Retriever`` to that empty retrieval — so
    the CLI generates with no network and no credential. Returns an equivalent provider for a direct
    ``draft()`` call to compare against.
    """
    prompt = _compose_prompt(request, RetrievalTrace())
    fixtures = {
        prompt_key("github", model, prompt): {"text": completion_text, "usage": {"total_tokens": 7}}
    }
    monkeypatch.setattr(
        "gmat_copilot.generate.select", lambda spec: (RecordedProvider(fixtures), model)
    )
    monkeypatch.setattr("gmat_copilot.generate.Retriever", _OfflineRetriever)
    return RecordedProvider(fixtures)


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "gmat-copilot" in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_validate_accepts_clean_script(tmp_path: Path, valid_script: str) -> None:
    script = tmp_path / "ok.script"
    script.write_text(valid_script, encoding="utf-8")
    assert main(["validate", str(script)]) == 0


def test_validate_rejects_broken_script(tmp_path: Path, invalid_script: str) -> None:
    script = tmp_path / "bad.script"
    script.write_text(invalid_script, encoding="utf-8")
    assert main(["validate", str(script)]) == 1


def test_draft_errors_cleanly_without_credentials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stub the retriever so the test needs no network (no embedder download); with no credential the
    # missing key must surface as a clean exit-2 error, not a traceback.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("gmat_copilot.generate.Retriever", _OfflineRetriever)
    assert main(["draft", "a 500 km LEO", "-m", "anthropic:claude-x"]) == 2
    assert "gmat-copilot:" in capsys.readouterr().err


def test_intent_writes_byte_identical_to_draft(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    # The DoD: the CLI's written script is byte-identical to the equivalent draft() call on the same
    # recorded provider.
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    provider = _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    expected = draft(request, model=model, provider=provider, retriever=_OfflineRetriever())

    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == expected.script
    captured = capsys.readouterr()
    assert "lint: clean" in captured.err
    assert str(out) in captured.err  # the summary names the file it wrote


def test_intent_defaults_output_to_mission_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    monkeypatch.chdir(tmp_path)
    assert main([request, "-m", f"github:{model}"]) == 0
    assert (tmp_path / "mission.script").read_text(encoding="utf-8").startswith("Create Spacecraft")


def test_intent_writes_to_stdout_with_dash(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    provider = _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    expected = draft(request, model=model, provider=provider, retriever=_OfflineRetriever())
    assert main([request, "-m", f"github:{model}", "-o", "-"]) == 0
    captured = capsys.readouterr()
    assert captured.out == expected.script  # the script went to stdout, unadorned
    assert "lint: clean" in captured.err


def test_intent_strict_rejection_exits_one_and_writes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    hallucinated_field_script: str,
) -> None:
    # A hallucinated field lints as a WARNING; strict (the default) must reject it (D5), exit
    # non-zero, and write no file.
    request = "a LEO with a mistyped field"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{hallucinated_field_script}```")
    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out)]) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "rejected" in err
    assert "warning(s)" in err


def test_intent_permissive_writes_with_warning_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    hallucinated_field_script: str,
) -> None:
    request = "a LEO with a mistyped field"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{hallucinated_field_script}```")
    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out), "--permissive"]) == 0
    assert out.exists()
    assert "warning(s)" in capsys.readouterr().err


def test_intent_without_model_lists_reachable_providers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No --model: draft() -> select(None) errors and lists reachable providers (D4); exit 2.
    assert main(["a 500 km LEO"]) == 2
    assert "no model selected" in capsys.readouterr().err.lower()


def test_draft_alias_matches_the_bare_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    # `gmat-copilot draft "<intent>"` is an alias of the bare form: same generate handler.
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    out = tmp_path / "mission.script"
    assert main(["draft", request, "-m", f"github:{model}", "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("Create Spacecraft")


def test_eval_recorded_replays_bundle(
    eval_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["eval", "--recorded", str(eval_bundle), "-m", "openai/gpt-4.1-mini"]) == 0
    out = capsys.readouterr().out
    assert "pass-rate: 80%" in out  # the frozen 51-prompt aggregate (41/51)
    assert "[easy" in out  # the per-prompt line shows the difficulty tier


def test_eval_with_no_mode_prints_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval"]) == 0
    assert "--recorded" in capsys.readouterr().err


def test_eval_live_without_prompts_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval", "--live"]) == 2
    assert "--prompts" in capsys.readouterr().err


def test_eval_live_errors_cleanly_without_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reach the generation provider with no token: a clean exit-2 ProviderError, not a traceback.
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("MODELS_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("gmat_copilot.generate.Retriever", _OfflineRetriever)
    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        '[{"id": "p", "request": "a LEO", "intent": "a LEO", "structural": {}}]',
        encoding="utf-8",
    )
    code = main(["eval", "--live", "--prompts", str(prompts), "-m", "github:openai/gpt-4.1-mini"])
    assert code == 2
    assert "gmat-copilot:" in capsys.readouterr().err


def test_eval_record_errors_cleanly_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --record loads prompts from DIR/prompts.json, then hits the same credential error path.
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("MODELS_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("gmat_copilot.generate.Retriever", _OfflineRetriever)
    (tmp_path / "prompts.json").write_text(
        '[{"id": "p", "request": "a LEO", "intent": "a LEO", "structural": {}}]',
        encoding="utf-8",
    )
    assert main(["eval", "--record", str(tmp_path), "-m", "github:openai/gpt-4.1-mini"]) == 2


_PROMPTS_JSON = '[{"id": "p", "request": "a LEO", "intent": "a LEO", "structural": {}}]'


def _one_outcome_report() -> EvalReport:
    """An EvalReport with a single passing outcome, for the report-printing CLI paths."""
    return EvalReport(
        outcomes=(
            PromptOutcome(
                id="p1",
                difficulty="easy",
                structural=StructuralResult(passed=True),
                judge=True,
                passed=True,
            ),
        )
    )


def test_eval_live_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The success path: with the live run stubbed, --live prints the report and exits 0.
    monkeypatch.setattr(
        "gmat_copilot.cli.run_live", lambda prompts, **kwargs: _one_outcome_report()
    )
    prompts = tmp_path / "prompts.json"
    prompts.write_text(_PROMPTS_JSON, encoding="utf-8")
    assert (
        main(["eval", "--live", "--prompts", str(prompts), "-m", "github:openai/gpt-4.1-mini"]) == 0
    )
    assert "pass-rate: 100%" in capsys.readouterr().out


def test_eval_record_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "gmat_copilot.cli.record_bundle",
        lambda prompts, bundle_dir, **kwargs: _one_outcome_report(),
    )
    (tmp_path / "prompts.json").write_text(_PROMPTS_JSON, encoding="utf-8")
    assert main(["eval", "--record", str(tmp_path), "-m", "github:openai/gpt-4.1-mini"]) == 0
    assert "pass-rate: 100%" in capsys.readouterr().out


def test_lint_summary_counts_each_severity() -> None:
    report = LintReport(
        diagnostics=(
            LintDiagnostic(rule="r1", severity=Severity.ERROR, message="m", line=1, column=1),
            LintDiagnostic(rule="r2", severity=Severity.WARNING, message="m", line=2, column=1),
            LintDiagnostic(rule="r3", severity=Severity.INFO, message="m", line=3, column=1),
        )
    )
    assert _lint_summary(report) == "1 error(s), 1 warning(s), 1 info(s)"


def test_lint_summary_clean() -> None:
    assert _lint_summary(LintReport()) == "clean"


# ------------------------------------------------------- dry-run / repair / provenance on the CLI


def _ok_dry_run() -> DryRunReport:
    return DryRunReport(tier="load", ok=True, converged=None, one_line="", raw_log="")


def _failed_dry_run() -> DryRunReport:
    return DryRunReport(
        tier="load",
        ok=False,
        converged=None,
        one_line='Gregorian date "01 Foo 2025 12:00:00.000" is not valid.',
        raw_log="",
    )


def test_dry_run_without_gmat_extra_errors_cleanly(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # --dry-run with the [gmat] extra absent: an eager, actionable exit-2 error, not a traceback.
    # The guard fires before any provider call, so this needs no credential and no recording.
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert main(["a 500 km LEO", "-m", "github:openai/gpt-4.1-mini", "--dry-run"]) == 2
    assert "[gmat]" in capsys.readouterr().err


def test_validate_dry_run_without_gmat_extra_errors_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    script = tmp_path / "ok.script"
    script.write_text(valid_script, encoding="utf-8")
    assert main(["validate", str(script), "--dry-run"]) == 2
    assert "[gmat]" in capsys.readouterr().err


def test_dry_run_summary_reports_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    # The [gmat] tier is mocked (the GMAT-free CI has no GMAT): a passing dry-run shows in the
    # summary and the script is written.
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("gmat_copilot.repair._dry_run", lambda script, **kwargs: _ok_dry_run())
    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out), "--dry-run"]) == 0
    assert out.exists()
    assert "dry-run: ok" in capsys.readouterr().err


def test_dry_run_failure_is_rejected_in_strict_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    # A lint-clean script whose dry-run fails is rejected (strict), exits 1, and writes nothing.
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("gmat_copilot.repair._dry_run", lambda script, **kwargs: _failed_dry_run())
    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out), "--dry-run"]) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "rejected" in err
    assert "dry-run failed at load" in err


def test_negative_repair_budget_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["a LEO", "-m", "github:openai/gpt-4.1-mini", "--repair", "-1"]) == 2
    assert "--repair" in capsys.readouterr().err


def _result_with_attempts(script: str, n: int) -> CopilotResult:
    """A result whose provenance records *n* draft attempts (n-1 retries), for the summary test."""
    lint = LintReport()
    attempts = tuple(
        DraftAttempt(
            script=script,
            lint=lint,
            dry_run=None,
            passed=(i == n - 1),
            feedback=(),
            feedback_tier=None,
            usage={"total_tokens": 1},
        )
        for i in range(n)
    )
    provenance = Provenance(
        request="a LEO",
        provider="github",
        model="m",
        retrieval=RetrievalTrace(),
        repair=RepairTrace(attempts=attempts, stop_reason="clean"),
        outcome=Outcome(winner=n - 1, passed=True, strict=True, usage={"total_tokens": n}),
    )
    return CopilotResult(
        script=script,
        lint=lint,
        retrieval=RetrievalTrace(),
        provider="github",
        model="m",
        usage={"total_tokens": n},
        dry_run=None,
        provenance=provenance,
    )


def test_repair_summary_reports_retries(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    # With --repair set, the summary reports the retries spent (attempts - 1).
    result = _result_with_attempts(valid_script, n=3)
    monkeypatch.setattr("gmat_copilot.cli.draft", lambda *args, **kwargs: result)
    out = tmp_path / "mission.script"
    assert main(["a LEO", "-m", "github:openai/gpt-4.1-mini", "-o", str(out), "--repair", "5"]) == 0
    assert "retries: 2" in capsys.readouterr().err


def test_provenance_flag_writes_sidecar(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out), "--provenance"]) == 0
    sidecar = out.with_name(out.name + ".copilot.json")
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["request"] == request
    assert sidecar.name in capsys.readouterr().err  # the summary names the sidecar it wrote


def test_no_provenance_sidecar_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    out = tmp_path / "mission.script"
    assert main([request, "-m", f"github:{model}", "-o", str(out)]) == 0
    assert not out.with_name(out.name + ".copilot.json").exists()


def test_provenance_to_stdout_errors(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    # --provenance has no file to sit beside when writing to stdout: a clean exit-2 error.
    request = "a 500 km circular LEO"
    model = "openai/gpt-4.1-mini"
    _install_recorded(monkeypatch, request, model, f"```script\n{valid_script}```")
    assert main([request, "-m", f"github:{model}", "-o", "-", "--provenance"]) == 2
    assert "--provenance" in capsys.readouterr().err


def test_validate_dry_run_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("gmat_copilot.cli.dry_run", lambda text, **kwargs: _ok_dry_run())
    script = tmp_path / "ok.script"
    script.write_text(valid_script, encoding="utf-8")
    assert main(["validate", str(script), "--dry-run"]) == 0
    assert "dry-run: ok" in capsys.readouterr().err


def test_validate_dry_run_failure_rejects(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    valid_script: str,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr("gmat_copilot.cli.dry_run", lambda text, **kwargs: _failed_dry_run())
    script = tmp_path / "ok.script"
    script.write_text(valid_script, encoding="utf-8")
    assert main(["validate", str(script), "--dry-run"]) == 1
    assert "dry-run: failed at load" in capsys.readouterr().err
