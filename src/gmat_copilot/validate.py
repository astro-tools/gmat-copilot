"""The lint validation gate — the v0.1 validator (decision D5).

Generated scripts are checked with the ``gmat-script`` static linter: GMAT-free, instant, and
deterministic. Strict mode rejects on lint ERROR *and* WARNING (every WARNING-level rule is a hard
GMAT load error); permissive mode returns the best-effort script with all diagnostics attached.

The dynamic gmat-run dry-run and the repair loop are a later, gated capability behind the ``[gmat]``
extra; this module is the GMAT-free tier.
"""

from __future__ import annotations

from gmat_script import lint as _lint

from .result import LintDiagnostic, LintReport

__all__ = ["validate"]


def validate(script: str, *, target_version: str | None = None) -> LintReport:
    """Lint *script* and return a :class:`~gmat_copilot.result.LintReport`.

    :param script: GMAT mission-script source text.
    :param target_version: GMAT catalogue version to lint against; defaults to the newest shipped
        catalogue.
    :returns: the diagnostics in source order. Use :meth:`LintReport.blocking` to apply the
        strict/permissive gate.
    """
    diagnostics = tuple(
        LintDiagnostic(
            rule=d.rule,
            severity=d.severity,
            message=d.message,
            line=d.start.line,
            column=d.start.column,
        )
        for d in _lint(script, target_version=target_version)
    )
    return LintReport(diagnostics=diagnostics)
