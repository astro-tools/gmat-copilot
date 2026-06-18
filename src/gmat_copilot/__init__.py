"""gmat-copilot — model-agnostic natural-language → GMAT ``.script`` generation.

Retrieval-grounded generation through a provider abstraction, with a static lint gate and a
two-layer evaluation suite. The public surface is :func:`draft` and the :class:`CopilotResult` it
returns; the package is GMAT-free for generation and validation.
"""

from __future__ import annotations

from .dryrun import GmatExtraNotInstalled, dry_run, require_gmat_extra
from .generate import DraftRejected, draft
from .provenance import Outcome, Provenance, read_sidecar, write_sidecar
from .result import (
    CopilotResult,
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
    "CopilotResult",
    "DraftAttempt",
    "DraftRejected",
    "DryRunReport",
    "GmatExtraNotInstalled",
    "LintDiagnostic",
    "LintReport",
    "Outcome",
    "Provenance",
    "RepairTrace",
    "RetrievalChunk",
    "RetrievalTrace",
    "Severity",
    "draft",
    "dry_run",
    "read_sidecar",
    "require_gmat_extra",
    "write_sidecar",
]
__version__ = "0.2.0"
