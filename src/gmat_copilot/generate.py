"""Prompt construction and the generation pipeline — the public ``draft`` entry point.

``draft`` ties the layers together: retrieve grounding from the corpus (``rag``), construct the
generation prompt, call the selected provider (``providers``), extract the ``.script`` from the
completion, validate it (``validate`` and — when enabled — the gmat-run dry-run), and return a
:class:`~gmat_copilot.result.CopilotResult`. The prompt pins an explicit output contract — a single
fenced GMAT ``.script`` grounded in the retrieved context, no prose — and extraction unwraps that
fence.

Generation is wrapped in a **bounded repair loop** (decision D13): a failing draft's diagnostics are
fed back and the model regenerates, up to a retry budget, stopping on the first clean/runnable draft
or on no-progress / oscillation. The budget defaults to ``0`` — a single pass, the v0.1 behaviour.
The strict/permissive gate then decides whether an unclean final draft is rejected or returned with
its diagnostics attached.
"""

from __future__ import annotations

import re

from .provenance import Outcome, Provenance
from .providers import Completion, Provider, ProviderError, select
from .rag import Retriever, assemble_context
from .repair import DryRunFn, aggregate_usage, build_repair_prompt, draft_hash, evaluate
from .result import CopilotResult, DraftAttempt, RepairTrace, RetrievalTrace

__all__ = ["DraftRejected", "draft"]


class DraftRejected(RuntimeError):
    """Strict :func:`draft` rejected the final draft for blocking diagnostics (decisions D5 / D13).

    Raised only after the repair budget is spent. The offending
    :class:`~gmat_copilot.result.CopilotResult` is attached as :attr:`result`, so the caller can
    inspect the script, its lint report, and any dry-run verdict.
    """

    def __init__(self, result: CopilotResult) -> None:
        self.result = result
        blocking = result.lint.blocking(strict=True)
        parts = []
        if blocking:
            parts.append(f"{len(blocking)} blocking lint diagnostic(s)")
        dry = result.dry_run
        if dry is not None and not dry.ok:
            parts.append(f"a dry-run failure at the {dry.tier} tier ({dry.one_line})")
        # A lint failure short-circuits the dry-run (decision D13), so exactly one part is present
        # whenever this is raised; the join is defensive.
        detail = " and ".join(parts)
        super().__init__(
            f"strict mode rejected the draft after the repair budget: {detail} "
            "(lint errors and warnings both block; use permissive mode to return the "
            "best-effort draft with diagnostics attached)"
        )


# The system framing: pins the task, the GMAT script shape, and the output contract so the model
# emits a valid script rather than prose or an invented format. The retrieved grounding curbs
# hallucinated resource/field names; the worked example below curbs the other failure mode — an
# invented procedural command syntax (`Prop.Propagate;`, `Report.Write;`), which the model otherwise
# guesses because the reference grounding describes resources but rarely shows command syntax.
_SYSTEM_PROMPT = (
    "You are a GMAT mission-script generator. Translate the user's request into a single, valid "
    "GMAT mission `.script`.\n"
    "\n"
    "A GMAT script has two parts: resource creation, then a mission sequence. Create every "
    "resource with `Create <Type> <Name>;` and set fields with `<Name>.<Field> = <value>;`, all "
    "before `BeginMissionSequence`. The mission commands come after it.\n"
    "\n"
    "Mission commands are standalone statements — never methods or fields on a resource. Do NOT "
    "write `Prop.Propagate;`, `Prop.PropagateFor = ...;`, `Report.Write;`, or "
    "`EndMissionSequence;`; none of those are GMAT. The command forms are:\n"
    "- Propagate: `Propagate <Propagator>(<Spacecraft>) {<StopCondition>};`, e.g. "
    "`Propagate Prop(Sat) {Sat.ElapsedDays = 1};` or `Propagate Prop(Sat) {Sat.Apoapsis};`.\n"
    "- Report:    `Report <ReportFile> <Param> <Param> ...;` — a ReportFile also lists outputs via "
    "`<rf>.Add = {...};`, and its filename field is `Filename`.\n"
    "- Maneuver:  `Maneuver <ImpulsiveBurn>(<Spacecraft>);`.\n"
    "- Target:    `Target <DC>; Vary <DC>(...); Achieve <DC>(...); EndTarget;`.\n"
    "\n"
    "Rules:\n"
    "- Output only the script — no prose, no explanation, no commentary outside the script.\n"
    "- A command's resources must exist: a `Propagate` needs a `Propagator`, a `Report` needs a "
    "`ReportFile`. Create everything a command references before `BeginMissionSequence`.\n"
    "- Use only real GMAT resource types, fields, and commands. Prefer the resource types and "
    "field names shown in the grounding context below over guessing.\n"
    "- Return the script inside a single fenced code block tagged `script`.\n"
    "\n"
    "Example of the required shape (a different mission — follow the syntax, not the values):\n"
    "Create Spacecraft Sat;\n"
    "Sat.DisplayStateType = Keplerian;\n"
    "Sat.SMA = 7000;\n"
    "Sat.ECC = 0.01;\n"
    "Sat.INC = 28.5;\n"
    "Create ForceModel FM;\n"
    "FM.PrimaryBodies = {Earth};\n"
    "Create Propagator Prop;\n"
    "Prop.FM = FM;\n"
    "Create ImpulsiveBurn dv;\n"
    "dv.Axes = VNB;\n"
    "dv.Element1 = 0.1;\n"
    "Create ReportFile rf;\n"
    "rf.Filename = 'out.txt';\n"
    "rf.Add = {Sat.Earth.SMA};\n"
    "BeginMissionSequence;\n"
    "Propagate Prop(Sat) {Sat.ElapsedSecs = 3600};\n"
    "Maneuver dv(Sat);\n"
    "Propagate Prop(Sat) {Sat.Apoapsis};\n"
    "Report rf Sat.Earth.SMA;"
)

# The closing reminder of the output contract — repeated after the request so it is the last thing
# the model reads before generating.
_OUTPUT_CONTRACT = (
    "Return only the GMAT `.script`, inside one ```script fenced code block, with nothing before "
    "or after it."
)

# A fenced code block with its language tag captured (```script / ```gmat / bare ```). The script
# the model emits under the output contract is unwrapped from such a block; extraction prefers a
# `script`/`gmat`-tagged block so a leading prose/plan fence cannot shadow the real mission.
_FENCE = re.compile(r"```(?P<tag>[^\n`]*)\n(?P<body>.*?)\n?```", re.DOTALL)

# Tags that mark the fence as the GMAT mission script (vs. a prose/plan/other block the model may
# emit first). Preferred over an untagged or otherwise-tagged block when several fences are present.
_SCRIPT_TAGS = frozenset({"script", "gmat"})


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
    """Return the ``.script`` from a completion, unwrapping the fenced block when one is present.

    The output contract asks for a single ``script``-tagged block. When more than one fence is
    present, a ``script``/``gmat``-tagged block is preferred over an untagged or prose-tagged one, so
    a model that prefixes its mission with an explanation fence cannot have that explanation extracted
    as the draft (it would otherwise lint clean and be accepted). Falls back to the first block, then
    — with no fence at all — to the text unchanged, so a contract violation surfaces as a lint failure
    (in strict mode) rather than being silently mangled.
    """
    matches = list(_FENCE.finditer(text))
    if not matches:
        return text
    for match in matches:
        if match.group("tag").strip().lower() in _SCRIPT_TAGS:
            return match.group("body").strip()
    return matches[0].group("body").strip()


def draft(
    request: str,
    *,
    model: str | None = None,
    strict: bool = True,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    retriever: Retriever | None = None,
    provider: Provider | None = None,
    repair: int = 0,
    dry_run: bool = False,
    gmat_root: str | None = None,
    dry_run_fn: DryRunFn | None = None,
) -> CopilotResult:
    """Generate a GMAT mission ``.script`` from a natural-language *request*.

    Orchestrates retrieve → generate → validate, wrapped in a bounded repair loop (decision D13):
    on a failing draft the failing tier's diagnostics are fed back and the model regenerates, up to
    *repair* attempts, stopping on the first clean/runnable draft or on no-progress / oscillation.
    Returns a :class:`~gmat_copilot.result.CopilotResult` for the final draft, with a versioned
    :class:`~gmat_copilot.provenance.Provenance` record (request, retrieval, the per-attempt
    history, and the outcome — decision D14) attached on ``provenance``.

    :param request: what the script should do, in natural language.
    :param model: the ``"provider:model"`` selector (decision D4 — there is no default; selection is
        always explicit). When *provider* is supplied this is the bare model name handed to it;
        otherwise it is resolved with :func:`~gmat_copilot.providers.select`, which errors and lists
        the reachable providers when it is ``None``.
    :param strict: reject the final draft if it does not validate clean — lint ERROR *and* WARNING
        both block (decision D5), and a dry-run failure blocks when the dynamic tier is enabled — by
        raising :class:`DraftRejected` once the budget is spent. Permissive (``strict=False``)
        returns the best-effort draft with every diagnostic attached.
    :param temperature: sampling temperature passed to the provider.
    :param max_tokens: maximum number of tokens to generate.
    :param retriever: corpus retriever used to ground generation; defaults to a
        :class:`~gmat_copilot.rag.Retriever`. Retrieval is computed once from *request* and reused
        across repair attempts.
    :param provider: model provider used to generate; defaults to the one *model* selects.
    :param repair: the retry budget for the repair loop (decision D13). ``0`` (the default) is a
        single pass — the v0.1 behaviour.
    :param dry_run: enable the dynamic gmat-run dry-run tier (decision D12) in validation; needs the
        ``[gmat]`` extra and a GMAT install. Off by default, keeping generation GMAT-free.
    :param gmat_root: GMAT install root forwarded to the dry-run (else ``GMAT_ROOT`` / discovery).
    :param dry_run_fn: a dynamic-tier dry-run to use in place of the real gmat-run subprocess (the
        eval's deterministic replay seam, decision D7); ``None`` uses the real dry-run.
    :raises DraftRejected: in strict mode, when the final draft still has blocking diagnostics.
    :raises ProviderError: when no model is resolved — either *model* is ``None`` with no provider
        to apply it to, or :func:`~gmat_copilot.providers.select` cannot resolve the selector.
    :raises ValueError: when *repair* is negative.
    :returns: the final draft's script, its lint report (and dry-run verdict), the retrieval trace,
        provider metadata, aggregate usage, and the provenance record on ``provenance``.
    """
    if repair < 0:
        raise ValueError(f"repair budget must be >= 0, got {repair}")
    if provider is None:
        provider, model = select(model)
    if model is None:
        raise ProviderError("no model selected: pass the model name for the supplied provider")

    retrieval = (retriever or Retriever()).retrieve(request)
    attempts: list[DraftAttempt] = []
    history: list[str] = []
    current_request = request
    stop_reason = "budget"
    last: Completion | None = None

    for attempt in range(repair + 1):
        prompt = _compose_prompt(current_request, retrieval)
        last = provider.complete(
            prompt, model=model, temperature=temperature, max_tokens=max_tokens
        )
        script = _extract_script(last.text)
        verdict = evaluate(script, dry_run=dry_run, gmat_root=gmat_root, dry_run_fn=dry_run_fn)
        attempts.append(
            DraftAttempt(
                script=script,
                lint=verdict.lint,
                dry_run=verdict.dry_run,
                passed=verdict.passed,
                feedback=verdict.feedback,
                feedback_tier=verdict.feedback_tier,
                usage=dict(last.usage),
            )
        )
        if verdict.passed:
            stop_reason = "clean"
            break
        script_id = draft_hash(script)
        if attempt > 0 and script_id == history[-1]:
            stop_reason = "no-progress"
            break
        if script_id in history:
            stop_reason = "oscillation"
            break
        history.append(script_id)
        if attempt == repair:
            stop_reason = "budget"
            break
        current_request = build_repair_prompt(request, script, verdict.feedback)

    assert last is not None  # range(repair + 1) runs at least once (repair >= 0)
    final = attempts[-1]
    usage = aggregate_usage(tuple(attempts))
    provenance = Provenance(
        request=request,
        provider=last.provider,
        model=last.model,
        retrieval=retrieval,
        repair=RepairTrace(attempts=tuple(attempts), stop_reason=stop_reason),
        outcome=Outcome(
            winner=len(attempts) - 1,
            passed=final.passed,
            strict=strict,
            usage=usage,
        ),
    )
    result = CopilotResult(
        script=final.script,
        lint=final.lint,
        retrieval=retrieval,
        provider=last.provider,
        model=last.model,
        usage=usage,
        dry_run=final.dry_run,
        provenance=provenance,
    )
    dry_failed = final.dry_run is not None and not final.dry_run.ok
    if strict and (final.lint.blocking(strict=True) or dry_failed):
        raise DraftRejected(result)
    return result
