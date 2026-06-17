"""The LLM-as-judge for the semantic layer (decision D6).

Two valid scripts of the same intent differ greatly in text, so the eval scores *intent*, not text.
The judge asks a free GitHub Models tier model for a strict binary verdict — does the candidate
script satisfy the prompt's intent? — and the protocol takes an N-of-M majority vote, failing on a
tie. Per-merge CI never calls the judge live: it replays recorded verdicts (decision D7); the live
path here produces those fixtures (the leaderboard and the ``workflow_dispatch`` full run also use
it).
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence

from ..providers import GitHubModelsProvider, Provider

__all__ = [
    "JUDGE_MODEL",
    "JUDGE_SYSTEM",
    "judge",
    "judge_verdicts",
    "majority",
    "parse_verdict",
]

JUDGE_MODEL = "openai/gpt-4.1-mini"

# The judge framing: a strict, intent-only rubric returning a constrained binary verdict. The
# provider protocol takes a single prompt, so the framing is folded into the message rather than
# carried as a separate system role (mirrors the generation prompt in ``generate.py``).
JUDGE_SYSTEM = (
    "You are a strict evaluator of GMAT mission scripts. Given a natural-language INTENT and a "
    "candidate GMAT .script, decide whether the script satisfies the intent. Judge ONLY against "
    "the intent and ignore stylistic differences. A script that is syntactically valid but models "
    "the wrong orbit, wrong inclination, wrong quantity, wrong maneuver direction, wrong target "
    "value, or wrong output format does NOT satisfy the intent. Respond with ONLY a JSON object: "
    '{"satisfies_intent": true or false, "reason": "<one short sentence>"}.'
)


def majority(verdicts: Sequence[bool | None]) -> bool | None:
    """Majority vote over *verdicts*, ignoring ``None``; FAIL on a tie (decision D6).

    :returns: the majority boolean, or ``None`` if there are no non-``None`` verdicts.
    """
    votes = [v for v in verdicts if v is not None]
    if not votes:
        return None
    trues = sum(1 for v in votes if v)
    falses = len(votes) - trues
    if trues == falses:
        return False  # FAIL on tie
    return trues > falses


def parse_verdict(content: str) -> bool | None:
    """Extract the binary verdict from a judge completion.

    Prefers the constrained ``{"satisfies_intent": bool}`` object; falls back to an unambiguous
    bare ``true``/``false`` in the prose. Returns ``None`` when the verdict cannot be read — a
    ``None`` is dropped by :func:`majority`, never counted as a vote.
    """
    try:
        obj = json.loads(content[content.index("{") : content.rindex("}") + 1])
    except ValueError:
        obj = None
    value = obj.get("satisfies_intent") if isinstance(obj, dict) else None
    if isinstance(value, bool):
        return value
    low = content.lower()
    if "true" in low and "false" not in low:
        return True
    if "false" in low and "true" not in low:
        return False
    return None


def _judge_prompt(intent: str, script: str) -> str:
    """Fold the rubric, the intent, and the candidate script into one judge prompt."""
    return f"{JUDGE_SYSTEM}\n\nINTENT:\n{intent}\n\nCANDIDATE SCRIPT:\n```\n{script}\n```"


def judge_verdicts(
    intent: str,
    script: str,
    *,
    model: str = JUDGE_MODEL,
    n: int = 3,
    provider: Provider | None = None,
    pace: float = 0.0,
) -> list[bool | None]:
    """Run the judge *n* times and return the raw per-run verdicts (decision D6).

    The list of verdicts is what the recorded bundle freezes; :func:`majority` reduces it to the
    gate decision. *pace* seconds are slept between calls to respect the free-tier per-minute budget
    when recording live; unit tests leave it at ``0``.

    :param provider: the model provider; defaults to a
        :class:`~gmat_copilot.providers.GitHubModelsProvider` (the free-tier path the judge is
        specified against, decision D7).
    """
    prov = provider if provider is not None else GitHubModelsProvider()
    prompt = _judge_prompt(intent, script)
    verdicts: list[bool | None] = []
    for index in range(n):
        if pace and index:
            time.sleep(pace)
        completion = prov.complete(prompt, model=model, temperature=0.0, max_tokens=200)
        verdicts.append(parse_verdict(completion.text))
    return verdicts


def judge(
    intent: str,
    script: str,
    *,
    model: str = JUDGE_MODEL,
    n: int = 3,
    provider: Provider | None = None,
    pace: float = 0.0,
) -> bool | None:
    """Run the judge *n* times on whether *script* satisfies *intent*; majority-vote (D6)."""
    return majority(judge_verdicts(intent, script, model=model, n=n, provider=provider, pace=pace))
