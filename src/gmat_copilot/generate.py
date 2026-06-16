"""Prompt construction and the generation pipeline — the public ``draft`` entry point.

``draft`` ties the layers together: retrieve grounding from the corpus (``rag``), construct the
prompt, call the selected provider (``providers``), validate the draft (``validate``), and return a
:class:`~gmat_copilot.result.CopilotResult`. Retrieval and the live provider calls are filled in by
their feature work; the orchestration, the strict/permissive gate (decision D5), and the result
assembly are real here and are exercised against injected stand-ins.
"""

from __future__ import annotations

from .providers import Provider, select
from .rag import Retriever
from .result import CopilotResult, RetrievalTrace
from .validate import validate

__all__ = ["DraftRejected", "draft"]


class DraftRejected(RuntimeError):
    """Strict :func:`draft` rejected a draft that did not lint clean (decision D5).

    The offending :class:`~gmat_copilot.result.CopilotResult` is attached as :attr:`result`, so the
    caller can inspect the script and its diagnostics.
    """

    def __init__(self, result: CopilotResult) -> None:
        self.result = result
        blocking = result.lint.blocking(strict=True)
        super().__init__(
            f"strict mode rejected the draft: {len(blocking)} blocking diagnostic(s) "
            "(lint errors and warnings both block; use permissive mode to return the "
            "best-effort draft with diagnostics attached)"
        )


def _compose_prompt(request: str, retrieval: RetrievalTrace) -> str:
    """Assemble the generation prompt from the *request* and the retrieved grounding.

    Minimal by design: the retrieved chunks are appended as grounding context. The full prompt
    template — system framing, examples, and the output contract — is built by the generation work.
    """
    if not retrieval.chunks:
        return request
    grounding = "\n\n".join(chunk.text for chunk in retrieval.chunks)
    return f"{request}\n\n# Grounding\n{grounding}"


def draft(
    request: str,
    *,
    model: str | None = None,
    strict: bool = True,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    retriever: Retriever | None = None,
    provider: Provider | None = None,
) -> CopilotResult:
    """Generate a GMAT mission ``.script`` from a natural-language *request*.

    Orchestrates retrieve → generate → validate and returns a
    :class:`~gmat_copilot.result.CopilotResult`.

    :param request: what the script should do, in natural language.
    :param model: the ``"provider:model"`` selector (decision D4 — there is no default; selection is
        always explicit). When *provider* is supplied this is the bare model name handed to it;
        otherwise it is resolved with :func:`~gmat_copilot.providers.select`, which errors and lists
        the reachable providers when it is ``None``.
    :param strict: reject a draft that does not lint clean — lint ERROR *and* WARNING both block
        (decision D5) — by raising :class:`DraftRejected`. Permissive (``strict=False``) returns the
        best-effort script with every diagnostic attached.
    :param temperature: sampling temperature passed to the provider.
    :param max_tokens: maximum number of tokens to generate.
    :param retriever: corpus retriever used to ground generation; defaults to a
        :class:`~gmat_copilot.rag.Retriever`.
    :param provider: model provider used to generate; defaults to the one *model* selects.
    :raises DraftRejected: in strict mode, when the draft does not lint clean.
    :returns: the generated script, its lint report, the retrieval trace, and provider metadata.
    """
    if provider is None:
        provider, model = select(model)
    if model is None:
        raise ValueError("model is required: pass the model name for the supplied provider")

    retrieval = (retriever or Retriever()).retrieve(request)
    prompt = _compose_prompt(request, retrieval)
    completion = provider.complete(
        prompt, model=model, temperature=temperature, max_tokens=max_tokens
    )
    report = validate(completion.text)
    result = CopilotResult(
        script=completion.text,
        lint=report,
        retrieval=retrieval,
        provider=completion.provider,
        model=completion.model,
        usage=completion.usage,
    )
    if strict and report.blocking(strict=True):
        raise DraftRejected(result)
    return result
