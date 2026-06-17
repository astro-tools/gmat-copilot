"""Prompt construction and the generation pipeline — the public ``draft`` entry point.

``draft`` ties the layers together: retrieve grounding from the corpus (``rag``), construct the
generation prompt, call the selected provider (``providers``), extract the ``.script`` from the
completion, validate it (``validate``), and return a
:class:`~gmat_copilot.result.CopilotResult`. The prompt pins an explicit output contract — a single
fenced GMAT ``.script`` grounded in the retrieved context, no prose — and extraction unwraps that
fence. Generation is single pass: the draft is generated and validated once, with no repair loop
(decision D5). The strict/permissive lint gate then decides whether an unclean draft is rejected
or returned with its diagnostics attached.
"""

from __future__ import annotations

import re

from .providers import Provider, select
from .rag import Retriever, assemble_context
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


# The system framing: pins the task and the output contract so the model emits a script rather than
# prose or an invented format. Grounding it in retrieved GMAT references curbs hallucinated names.
_SYSTEM_PROMPT = (
    "You are a GMAT mission-script generator. Translate the user's request into a single, valid "
    "GMAT mission `.script`.\n"
    "\n"
    "Rules:\n"
    "- Output only the script — no prose, no explanation, no commentary outside the script.\n"
    "- Declare every resource with a `Create` statement before any command references it, and "
    "place all resource setup before `BeginMissionSequence`.\n"
    "- Use only real GMAT resource types, fields, and commands. Prefer the resource types and "
    "field names shown in the grounding context below over guessing.\n"
    "- Return the script inside a single fenced code block tagged `script`."
)

# The closing reminder of the output contract — repeated after the request so it is the last thing
# the model reads before generating.
_OUTPUT_CONTRACT = (
    "Return only the GMAT `.script`, inside one ```script fenced code block, with nothing before "
    "or after it."
)

# A fenced code block, optionally language-tagged (```script / ```gmat / bare ```). The script the
# model emits under the output contract is unwrapped from the first such block.
_FENCE = re.compile(r"```[^\n`]*\n(?P<body>.*?)\n?```", re.DOTALL)


def _compose_prompt(request: str, retrieval: RetrievalTrace) -> str:
    """Assemble the single generation prompt from the *request* and the retrieved grounding.

    Folds the system framing, the source-attributed grounding block built from the retrieval trace
    (omitted when retrieval is empty), the request, and a closing restatement of the output contract
    into one message. The provider protocol takes a single ``prompt`` string, so there is no
    system/user role split to carry the framing separately.
    """
    sections = [_SYSTEM_PROMPT]
    context = assemble_context(retrieval)
    if context:
        sections.append(f"# Grounding context\nGMAT references for this request:\n\n{context}")
    sections.append(f"# Request\n{request}")
    sections.append(f"# Output\n{_OUTPUT_CONTRACT}")
    return "\n\n".join(sections)


def _extract_script(text: str) -> str:
    """Return the ``.script`` from a completion, unwrapping a fenced block when one is present.

    The output contract asks for a single fenced block; this pulls its content, dropping the fence
    and any language tag. A completion with no fence is returned unchanged, so a contract violation
    surfaces as a lint failure (in strict mode) rather than being silently mangled.
    """
    match = _FENCE.search(text)
    if match is None:
        return text
    return match.group("body").strip()


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
    script = _extract_script(completion.text)
    report = validate(script)
    result = CopilotResult(
        script=script,
        lint=report,
        retrieval=retrieval,
        provider=completion.provider,
        model=completion.model,
        usage=completion.usage,
    )
    if strict and report.blocking(strict=True):
        raise DraftRejected(result)
    return result
