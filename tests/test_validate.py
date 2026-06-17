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


def test_hallucinated_field_is_a_real_warning(hallucinated_field_script: str) -> None:
    # Driven through the real gmat-script linter, not a hand-built diagnostic: a hallucinated
    # field is a WARNING that strict rejects and permissive tolerates (D5).
    report = validate(hallucinated_field_script)
    assert not report.clean
    assert report.errors == ()
    assert len(report.warnings) == 1
    warning = report.warnings[0]
    assert warning.rule == "unknown-field"
    assert warning.severity is Severity.WARNING
    assert warning.line >= 1
    assert warning.column >= 1
    assert "DryMas" in warning.message  # the linter's message is mapped through faithfully
    assert report.blocking(strict=True) == (warning,)
    assert report.blocking(strict=False) == ()


def test_hallucinated_resource_is_a_real_error(hallucinated_resource_script: str) -> None:
    # An invented resource type is an ERROR — strict rejects it; permissive returns it attached.
    report = validate(hallucinated_resource_script)
    assert not report.clean
    assert len(report.errors) == 1
    error = report.errors[0]
    assert error.rule == "unknown-resource-type"
    assert error.severity is Severity.ERROR
    assert "Satellite" in error.message
    assert report.blocking(strict=True) == (error,)
    assert report.blocking(strict=False) == ()
