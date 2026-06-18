"""The result schema returned by :func:`gmat_copilot.draft` (decision D10).

One stable contract carries everything a generation request produces: the generated ``.script``
text, the lint report, the retrieval trace, and the provider/model/usage that produced it. The
``provenance`` field carries the versioned record of how the draft was produced — the request, the
retrieved chunks, the draft history, and the outcome (decision D14) — and :meth:`CopilotResult.save`
can serialise it to a ``.copilot.json`` sidecar next to the written script.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gmat_script import Severity

__all__ = [
    "CopilotResult",
    "DraftAttempt",
    "DryRunReport",
    "LintDiagnostic",
    "LintReport",
    "RepairTrace",
    "RetrievalChunk",
    "RetrievalTrace",
    "Severity",
]


@dataclass(frozen=True, slots=True)
class LintDiagnostic:
    """One linter finding mapped from a ``gmat_script`` diagnostic: rule, severity, and location."""

    rule: str
    severity: Severity
    message: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class LintReport:
    """The lint diagnostics for a script, in source order, with severity-filtered views.

    The strict/permissive *decision* lives in the validator (decision D5); this is the raw report.
    """

    diagnostics: tuple[LintDiagnostic, ...] = ()

    @property
    def clean(self) -> bool:
        """True when the linter reported nothing at all."""
        return not self.diagnostics

    @property
    def errors(self) -> tuple[LintDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[LintDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.WARNING)

    @property
    def infos(self) -> tuple[LintDiagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.INFO)

    def blocking(self, *, strict: bool) -> tuple[LintDiagnostic, ...]:
        """Diagnostics that reject a draft under the given mode (decision D5).

        Strict rejects on ERROR *and* WARNING — every WARNING-level rule is a hard GMAT load
        error. Permissive never blocks: it returns the best-effort script with all diagnostics
        attached.
        """
        if not strict:
            return ()
        return tuple(
            d for d in self.diagnostics if d.severity in (Severity.ERROR, Severity.WARNING)
        )


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """The dynamic gmat-run dry-run finding for a script — a separate tier from the lint report.

    The dry-run runs only on a lint-clean script (decision D12): ``Mission.load`` is the config
    tier, and ``mission.run`` + ``Results.converged`` the execution tier, entered only when the
    script has a solver (``Target`` / ``Optimize``). Dry-run findings do **not** merge into
    :class:`LintReport` — lint diagnostics are precise (rule / severity / line / column) and a
    dry-run finding is coarser, so it lands here. ``ok`` is the blocking signal: a not-``ok`` report
    rejects in strict mode, just as a blocking lint diagnostic does.
    """

    #: The tier the verdict came from: ``"load"`` (config) or ``"run"`` (execution); ``"crash"`` /
    #: ``"timeout"`` when the dry-run subprocess died or exceeded its wall-clock budget.
    tier: str
    #: True when the script loads (and, if a solver is present, runs and converges).
    ok: bool
    #: Per-solver convergence from ``Results.converged`` (solver name -> converged), or ``None``
    #: when the execution tier was not entered (no solver, or the dry-run failed at load).
    converged: dict[str, bool] | None
    #: One actionable, path-free line distilled from GMAT's diagnostics; ``""`` when ``ok``.
    one_line: str
    #: The raw GMAT log the one-line was distilled from (path-sanitised); ``""`` when ``ok``.
    raw_log: str


@dataclass(frozen=True, slots=True)
class RetrievalChunk:
    """One corpus chunk surfaced by the retriever, with its source and similarity score."""

    source: str
    score: float
    text: str


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    """The corpus chunks used to ground a generation, most-relevant first."""

    chunks: tuple[RetrievalChunk, ...] = ()


@dataclass(frozen=True, slots=True)
class DraftAttempt:
    """One iteration of the repair loop (decision D13): a draft and how it validated.

    The loop generates a draft, lints it, and — when the dynamic tier is enabled and lint is clean —
    dry-runs it; ``feedback`` is what was fed into the next attempt's repair prompt.
    """

    script: str
    lint: LintReport
    #: The dynamic-tier verdict, when it ran (lint-clean and the dry-run enabled); else ``None``.
    dry_run: DryRunReport | None
    #: True when the draft is lint-clean and (if the dynamic tier ran) the dry-run is ``ok``.
    passed: bool
    #: The diagnostics fed into the next attempt — empty when the draft passed.
    feedback: tuple[str, ...]
    #: Which tier produced the feedback: ``"lint"`` / ``"load"`` / ``"run"`` / ... or ``None``.
    feedback_tier: str | None
    #: The generation usage for this attempt (token counts).
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RepairTrace:
    """The repair loop's per-attempt history and why it stopped (decision D13).

    Attached to :attr:`CopilotResult.provenance` as the substrate the v0.2 provenance sidecar (D14)
    formalises into a versioned record.
    """

    attempts: tuple[DraftAttempt, ...]
    #: Why the loop stopped: ``"clean"`` / ``"budget"`` / ``"no-progress"`` / ``"oscillation"``.
    stop_reason: str


@dataclass(frozen=True, slots=True)
class CopilotResult:
    """Everything a :func:`gmat_copilot.draft` call produces (decision D10)."""

    script: str
    lint: LintReport
    retrieval: RetrievalTrace
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    #: The dynamic dry-run verdict for the final draft, when the dry-run tier ran (decision D12);
    #: ``None`` when the dynamic tier was disabled or never reached (lint blocked first).
    dry_run: DryRunReport | None = None
    # The versioned provenance record (a ``provenance.Provenance``) once the loop runs — it wraps
    # the D13 repair trace with the request, provider/model, retrieval, and outcome (decision D14).
    # Typed loosely so that later enrichment is not a schema break.
    provenance: object | None = None

    def save(self, path: str | Path, *, sidecar: bool = False) -> Path:
        """Write the generated :attr:`script` to *path* (UTF-8); return the written path.

        With ``sidecar=True`` also write the provenance record (decision D14) as a ``.copilot.json``
        file next to the script (``<path>.copilot.json``). The sidecar is written only on request,
        never silently; it needs a result from :func:`gmat_copilot.draft` (whose :attr:`provenance`
        is populated).

        :raises TypeError: when ``sidecar=True`` but :attr:`provenance` is not a populated record
            (e.g. a hand-built result).
        """
        target = Path(path)
        if sidecar:
            from .provenance import Provenance, sidecar_path, write_sidecar

            # Validate before writing anything, so a provenance-less result fails cleanly rather than
            # leaving an orphan .script on disk next to the raised TypeError.
            if not isinstance(self.provenance, Provenance):
                raise TypeError(
                    "save(sidecar=True) needs a provenance-bearing result from draft(); "
                    f"this result's provenance is {type(self.provenance).__name__}"
                )
            # Pin LF so the saved script matches the LF copy embedded in its sidecar (and the project
            # convention of not normalising .script endings), instead of getting CRLF on Windows.
            target.write_text(self.script, encoding="utf-8", newline="\n")
            write_sidecar(self.provenance, sidecar_path(target))
            return target
        target.write_text(self.script, encoding="utf-8", newline="\n")
        return target
