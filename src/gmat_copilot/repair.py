"""The bounded repair loop's building blocks (decision D13).

The loop itself lives in :func:`gmat_copilot.generate.draft` (it owns prompt construction and the
provider call); this module supplies the pieces it needs: a combined lint-then-dry-run
:func:`evaluate`, the :func:`build_repair_prompt` that feeds a failing draft's diagnostics back to
the model, and small helpers for usage aggregation and the no-progress / oscillation hash check.

Validation is **lint-first** (decision D13): lint is precise and free, so a lint failure is reported
without paying for the dry-run; the dry-run one-line is the backstop for the
lint-clean-but-unrunnable drafts the loop exists for. ``evaluate`` calls the dynamic tier only when
it is enabled and the draft is lint-clean, so the GMAT-free path never touches gmat-run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .dryrun import dry_run as _dry_run
from .result import DraftAttempt, DryRunReport, LintDiagnostic, LintReport
from .validate import validate

__all__ = [
    "Verdict",
    "aggregate_usage",
    "build_repair_prompt",
    "draft_hash",
    "evaluate",
]


@dataclass(frozen=True, slots=True)
class Verdict:
    """The outcome of validating one draft: pass/fail plus the diagnostics to feed forward."""

    passed: bool
    lint: LintReport
    dry_run: DryRunReport | None
    feedback: tuple[str, ...]
    feedback_tier: str | None


def _lint_line(diagnostic: LintDiagnostic) -> str:
    """One feedback line for a blocking lint diagnostic: severity, rule, location, message."""
    return (
        f"{diagnostic.severity.name.lower()} [{diagnostic.rule}] "
        f"line {diagnostic.line}: {diagnostic.message}"
    )


def evaluate(
    script: str,
    *,
    dry_run: bool,
    gmat_root: str | None = None,
    timeout: float = 300.0,
) -> Verdict:
    """Validate *script* lint-first, then (if enabled and lint-clean) dry-run it (decision D13).

    A draft passes when it is lint-clean — no ERROR *and* no WARNING, every WARNING being a hard
    GMAT load error (decision D5) — and, when *dry_run* is enabled, the dynamic tier is ``ok``. On
    failure the verdict carries the failing tier's diagnostics as feedback for the next attempt.

    :param script: the draft to validate.
    :param dry_run: whether to run the dynamic gmat-run tier on a lint-clean draft.
    :param gmat_root: GMAT install root forwarded to the dry-run (else ``GMAT_ROOT`` / discovery).
    :param timeout: wall-clock budget forwarded to the dry-run.
    """
    report = validate(script)
    blocking = report.blocking(strict=True)
    if blocking:
        return Verdict(False, report, None, tuple(_lint_line(d) for d in blocking), "lint")
    if not dry_run:
        return Verdict(True, report, None, (), None)
    dr = _dry_run(script, gmat_root=gmat_root, timeout=timeout)
    if dr.ok:
        return Verdict(True, report, dr, (), None)
    feedback = (dr.one_line,) if dr.one_line else ("the dry-run failed",)
    return Verdict(False, report, dr, feedback, dr.tier)


def build_repair_prompt(request: str, prev_script: str, feedback: tuple[str, ...]) -> str:
    """The repair request: the original intent + the failing draft + the diagnostics to fix.

    The result is a new request string fed back through the normal generation prompt (system
    framing, retrieval grounding, output contract), so a repair attempt is an ordinary generation
    that additionally sees the prior attempt and why it failed.
    """
    bullets = "\n".join(f"- {line}" for line in feedback)
    return (
        f"{request}\n\n"
        "A previous attempt produced the script below, but it failed validation. Return a "
        "corrected, complete script that fixes every problem listed.\n\n"
        f"```script\n{prev_script}\n```\n\n"
        f"Problems to fix:\n{bullets}"
    )


def draft_hash(script: str) -> str:
    """A stable content hash of a draft, for the no-progress / oscillation stop conditions."""
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


def aggregate_usage(attempts: tuple[DraftAttempt, ...]) -> dict[str, int]:
    """Sum the per-attempt token usage across the loop, key by key."""
    total: dict[str, int] = {}
    for attempt in attempts:
        for key, value in attempt.usage.items():
            total[key] = total.get(key, 0) + value
    return total
