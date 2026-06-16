"""gmat-copilot — model-agnostic natural-language → GMAT ``.script`` generation.

Retrieval-grounded generation through a provider abstraction, with a static lint gate and a
two-layer evaluation suite. The public surface is :func:`draft` and the :class:`CopilotResult` it
returns; the package is GMAT-free for generation and validation.
"""

from __future__ import annotations

from .generate import DraftRejected, draft
from .result import (
    CopilotResult,
    LintDiagnostic,
    LintReport,
    RetrievalChunk,
    RetrievalTrace,
    Severity,
)

__all__ = [
    "CopilotResult",
    "DraftRejected",
    "LintDiagnostic",
    "LintReport",
    "RetrievalChunk",
    "RetrievalTrace",
    "Severity",
    "draft",
]
__version__ = "0.1.0"
