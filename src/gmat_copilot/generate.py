"""Prompt construction and the generation pipeline — the public ``draft`` entry point.

``draft`` ties the layers together: retrieve grounding from the corpus (``rag``), construct the
prompt, call the selected provider (``providers``), validate the draft (``validate``), and return a
:class:`~gmat_copilot.result.CopilotResult`. The pipeline body is filled in by the generation
feature work; this module pins the public signature the library and CLI depend on.
"""

from __future__ import annotations

from .result import CopilotResult

__all__ = ["draft"]


def draft(
    request: str,
    *,
    model: str,
    strict: bool = True,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> CopilotResult:
    """Generate a GMAT mission ``.script`` from a natural-language *request*.

    :param request: what the script should do, in natural language.
    :param model: the provider/model selector, ``"provider:model"`` (decision D4 — there is no
        default; selection is always explicit).
    :param strict: reject a draft that does not lint clean (no errors *or* warnings); permissive
        returns the best-effort script with diagnostics attached (decision D5).
    :param temperature: sampling temperature passed to the provider.
    :param max_tokens: maximum tokens to generate.
    :returns: the generated script, its lint report, the retrieval trace, and provider metadata.
    """
    raise NotImplementedError(
        "the generation pipeline is not wired yet; the scaffold pins the public surface. "
        "Retrieval, prompt construction, and provider calls land with the generation work"
    )
