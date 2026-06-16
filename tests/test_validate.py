"""The lint validation gate and the strict/permissive contract (decision D5)."""

from __future__ import annotations

from gmat_copilot import LintReport, Severity
from gmat_copilot.result import LintDiagnostic
from gmat_copilot.validate import validate


def test_clean_script_has_no_diagnostics(valid_script: str) -> None:
    report = validate(valid_script)
    assert report.clean
    assert report.blocking(strict=True) == ()
    assert report.blocking(strict=False) == ()


def test_error_blocks_in_strict_but_not_permissive(invalid_script: str) -> None:
    report = validate(invalid_script)
    assert report.errors  # a hard parse error
    assert report.blocking(strict=True)  # strict rejects
    assert report.blocking(strict=False) == ()  # permissive never blocks (D5)


def test_strict_rejects_warnings_but_not_infos() -> None:
    warning = LintDiagnostic(
        rule="unknown-field", severity=Severity.WARNING, message="...", line=1, column=1
    )
    info = LintDiagnostic(
        rule="unused-resource", severity=Severity.INFO, message="...", line=2, column=1
    )
    report = LintReport(diagnostics=(warning, info))

    blocking = report.blocking(strict=True)
    assert warning in blocking  # every WARNING is a hard GMAT load error (D5)
    assert info not in blocking
    assert report.blocking(strict=False) == ()
    assert report.warnings == (warning,)
    assert report.infos == (info,)
    assert not report.clean


def test_diagnostics_carry_location(invalid_script: str) -> None:
    report = validate(invalid_script)
    diagnostic = report.diagnostics[0]
    assert diagnostic.line >= 1
    assert diagnostic.column >= 1
    assert diagnostic.rule
