"""The versioned provenance record and its ``.copilot.json`` sidecar (decision D14).

D10 reserved a ``provenance`` field on :class:`~gmat_copilot.result.CopilotResult`; D13 filled it
with a :class:`~gmat_copilot.result.RepairTrace` (the per-attempt draft history). D14 formalises
that into a *versioned* record of the whole generation: the request, the resolved provider / model,
the retrieved grounding, the draft history, and the outcome — and serialises it to a
``.copilot.json`` sidecar written next to a saved script (e.g. ``mission.script.copilot.json``).

The in-memory :class:`Provenance` composes the existing dataclasses (it nests the ``RepairTrace``
D13 already builds); the on-disk JSON follows D14's flat schema — ``schema_version``, ``request``,
``provider``, ``model``, ``retrieval``, ``drafts``, ``outcome`` — and :func:`to_json_dict` /
:func:`from_json_dict` map between the two. The JSON is stable (sorted keys, a stamped
``schema_version``), so a recorded sidecar diffs cleanly, and it carries **no credentials**: the
record only ever holds the request, the provider / model *names*, the retrieval trace, the drafts,
and token usage — there is no field a key could enter through.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .result import (
    DraftAttempt,
    DryRunReport,
    LintDiagnostic,
    LintReport,
    RepairTrace,
    RetrievalChunk,
    RetrievalTrace,
    Severity,
)

__all__ = [
    "SCHEMA_VERSION",
    "Outcome",
    "Provenance",
    "dumps",
    "from_json_dict",
    "read_sidecar",
    "sidecar_path",
    "to_json_dict",
    "write_sidecar",
]

#: The provenance schema version: the writer stamps it and the reader checks it, so later additions
#: are additive rather than breaking (decision D14).
SCHEMA_VERSION = 1

#: The suffix appended to a saved script's filename to name its sidecar (``<script>.copilot.json``).
SIDECAR_SUFFIX = ".copilot.json"


@dataclass(frozen=True, slots=True)
class Outcome:
    """Which draft won and how the run ended (decision D14).

    ``winner`` indexes the final (returned) draft in :attr:`Provenance.repair`'s attempts — always
    the last attempt, recorded explicitly so the sidecar is self-describing. ``passed`` is whether
    that draft validated clean (lint, plus the dry-run when it ran); ``strict`` records the active
    mode, so a reader can tell a strict rejection (``passed=False, strict=True``) from a
    permissive best-effort return (``passed=False, strict=False``). ``usage`` is the aggregate token
    total across every attempt.
    """

    winner: int
    passed: bool
    strict: bool
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Provenance:
    """A versioned record of how a draft was produced (decision D14).

    Populated in memory by :func:`gmat_copilot.draft` for every run — it is the trace the result
    already holds — and serialised to a ``.copilot.json`` sidecar only on request by the saving
    surface (:meth:`gmat_copilot.CopilotResult.save`). Composes the existing
    :class:`~gmat_copilot.result.RetrievalTrace` and :class:`~gmat_copilot.result.RepairTrace`; the
    per-attempt draft history is :attr:`repair`'s ``attempts``.
    """

    request: str
    provider: str
    model: str
    retrieval: RetrievalTrace
    repair: RepairTrace
    outcome: Outcome
    schema_version: int = SCHEMA_VERSION


# ------------------------------------------------------------------------ serialisation (to dict)


def _retrieval_to_dict(trace: RetrievalTrace) -> dict[str, Any]:
    return {
        "chunks": [{"source": c.source, "score": c.score, "text": c.text} for c in trace.chunks]
    }


def _lint_to_dict(report: LintReport) -> dict[str, Any]:
    return {
        "diagnostics": [
            {
                "rule": d.rule,
                "severity": d.severity.value,
                "message": d.message,
                "line": d.line,
                "column": d.column,
            }
            for d in report.diagnostics
        ]
    }


def _dry_run_to_dict(report: DryRunReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "tier": report.tier,
        "ok": report.ok,
        "converged": report.converged,
        "one_line": report.one_line,
        "raw_log": report.raw_log,
    }


def _attempt_to_dict(attempt: DraftAttempt) -> dict[str, Any]:
    return {
        "script": attempt.script,
        "lint": _lint_to_dict(attempt.lint),
        "dry_run": _dry_run_to_dict(attempt.dry_run),
        "passed": attempt.passed,
        "feedback": list(attempt.feedback),
        "feedback_tier": attempt.feedback_tier,
        "usage": dict(attempt.usage),
    }


def to_json_dict(provenance: Provenance) -> dict[str, Any]:
    """Render *provenance* to D14's flat JSON shape (the draft history flattened to ``drafts``)."""
    return {
        "schema_version": provenance.schema_version,
        "request": provenance.request,
        "provider": provenance.provider,
        "model": provenance.model,
        "retrieval": _retrieval_to_dict(provenance.retrieval),
        "drafts": [_attempt_to_dict(a) for a in provenance.repair.attempts],
        "outcome": {
            "winner": provenance.outcome.winner,
            "passed": provenance.outcome.passed,
            "strict": provenance.outcome.strict,
            "stop_reason": provenance.repair.stop_reason,
            "usage": dict(provenance.outcome.usage),
        },
    }


# ----------------------------------------------------------------------- serialisation (from dict)


def _retrieval_from_dict(data: dict[str, Any]) -> RetrievalTrace:
    return RetrievalTrace(
        chunks=tuple(
            RetrievalChunk(source=c["source"], score=c["score"], text=c["text"])
            for c in data["chunks"]
        )
    )


def _lint_from_dict(data: dict[str, Any]) -> LintReport:
    return LintReport(
        diagnostics=tuple(
            LintDiagnostic(
                rule=d["rule"],
                severity=Severity(d["severity"]),
                message=d["message"],
                line=d["line"],
                column=d["column"],
            )
            for d in data["diagnostics"]
        )
    )


def _dry_run_from_dict(data: dict[str, Any] | None) -> DryRunReport | None:
    if data is None:
        return None
    converged = data["converged"]
    return DryRunReport(
        tier=data["tier"],
        ok=data["ok"],
        converged=None if converged is None else {str(k): bool(v) for k, v in converged.items()},
        one_line=data["one_line"],
        raw_log=data["raw_log"],
    )


def _attempt_from_dict(data: dict[str, Any]) -> DraftAttempt:
    return DraftAttempt(
        script=data["script"],
        lint=_lint_from_dict(data["lint"]),
        dry_run=_dry_run_from_dict(data["dry_run"]),
        passed=data["passed"],
        feedback=tuple(data["feedback"]),
        feedback_tier=data["feedback_tier"],
        usage={str(k): int(v) for k, v in data["usage"].items()},
    )


def from_json_dict(data: dict[str, Any]) -> Provenance:
    """Reconstruct a :class:`Provenance` from D14's JSON shape, checking the schema version.

    :raises ValueError: when ``schema_version`` is absent or not :data:`SCHEMA_VERSION` — a newer
        sidecar than this reader understands.
    """
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported provenance schema_version {version!r}; this reader writes "
            f"and understands version {SCHEMA_VERSION}"
        )
    outcome = data["outcome"]
    attempts = tuple(_attempt_from_dict(a) for a in data["drafts"])
    return Provenance(
        request=data["request"],
        provider=data["provider"],
        model=data["model"],
        retrieval=_retrieval_from_dict(data["retrieval"]),
        repair=RepairTrace(attempts=attempts, stop_reason=outcome["stop_reason"]),
        outcome=Outcome(
            winner=outcome["winner"],
            passed=outcome["passed"],
            strict=outcome["strict"],
            usage={str(k): int(v) for k, v in outcome["usage"].items()},
        ),
        schema_version=version,
    )


# ------------------------------------------------------------------------------------- sidecar I/O


def dumps(provenance: Provenance) -> str:
    """Serialise *provenance* to stable JSON text — sorted keys, indented, trailing newline.

    Sorted keys make a recorded sidecar diff cleanly run to run; ``ensure_ascii=False`` keeps any
    Unicode in the script or feedback readable (the sidecar is a UTF-8 file, not console output).
    """
    body = json.dumps(to_json_dict(provenance), sort_keys=True, indent=2, ensure_ascii=False)
    return f"{body}\n"


def sidecar_path(script_path: str | Path) -> Path:
    """The sidecar path for a saved script: ``<script>`` -> ``<script>.copilot.json`` (D14)."""
    target = Path(script_path)
    return target.with_name(target.name + SIDECAR_SUFFIX)


def write_sidecar(provenance: Provenance, path: str | Path) -> Path:
    """Write *provenance* as JSON to *path* (UTF-8, ``\\n`` newlines); return the written path.

    *path* is written verbatim — derive the conventional location with :func:`sidecar_path`.
    """
    out = Path(path)
    out.write_text(dumps(provenance), encoding="utf-8", newline="\n")
    return out


def read_sidecar(path: str | Path) -> Provenance:
    """Read a ``.copilot.json`` sidecar back into a :class:`Provenance` (the inverse of writing)."""
    return from_json_dict(json.loads(Path(path).read_text(encoding="utf-8")))
