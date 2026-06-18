"""The result schema: ``save()`` and the strict/permissive lint-blocking views (D10 / D5)."""

from __future__ import annotations

from pathlib import Path

from gmat_copilot import (
    CopilotResult,
    LintDiagnostic,
    LintReport,
    RetrievalTrace,
    Severity,
)


def _result(script: str, diagnostics: tuple[LintDiagnostic, ...] = ()) -> CopilotResult:
    return CopilotResult(
        script=script,
        lint=LintReport(diagnostics=diagnostics),
        retrieval=RetrievalTrace(),
        provider="recorded",
        model="m",
    )


def test_save_round_trips(tmp_path: Path) -> None:
    result = _result("Create Spacecraft Sat;\n")
    out = result.save(tmp_path / "mission.script")
    assert out == tmp_path / "mission.script"
    assert out.read_text(encoding="utf-8") == "Create Spacecraft Sat;\n"


def test_save_accepts_a_string_path(tmp_path: Path) -> None:
    result = _result("BeginMissionSequence;\n")
    out = result.save(str(tmp_path / "m.script"))
    assert out.read_text(encoding="utf-8") == "BeginMissionSequence;\n"


def test_save_writes_lf_line_endings(tmp_path: Path) -> None:
    # The script is written with LF on every platform (newline="\n"), so it matches the LF copy
    # embedded in its sidecar and is not silently rewritten to CRLF on Windows. read_text would
    # translate CRLF->LF and hide a regression, so assert on the raw bytes.
    result = _result("Create Spacecraft Sat;\nBeginMissionSequence;\n")
    out = result.save(tmp_path / "mission.script")
    assert b"\r\n" not in out.read_bytes()
    assert out.read_bytes() == b"Create Spacecraft Sat;\nBeginMissionSequence;\n"


def test_blocking_strict_includes_errors_and_warnings() -> None:
    report = LintReport(
        diagnostics=(
            LintDiagnostic("syntax-error", Severity.ERROR, "boom", 1, 1),
            LintDiagnostic("unknown-field", Severity.WARNING, "huh", 2, 1),
            LintDiagnostic("unused-resource", Severity.INFO, "fyi", 3, 1),
        )
    )
    # Strict blocks on ERROR and WARNING, but not the advisory INFO (decision D5).
    assert len(report.blocking(strict=True)) == 2
    assert report.blocking(strict=False) == ()
    assert not report.clean
    assert report.errors[0].rule == "syntax-error"
    assert report.warnings[0].rule == "unknown-field"
    assert report.infos[0].rule == "unused-resource"


def test_clean_report_has_no_diagnostics() -> None:
    assert LintReport().clean
    assert LintReport().blocking(strict=True) == ()
