"""The LLM-as-judge for the semantic layer (decision D6).

Two valid scripts of the same intent differ greatly in text, so the eval scores *intent*, not text.
The judge returns a strict binary verdict; the protocol takes an N-of-M majority vote and fails on a
tie. The default judge is a free GitHub Models tier model. The live call is wired by the eval-suite
work; per-merge CI replays recorded verdicts (decision D7), so this module also provides the vote.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["JUDGE_MODEL", "judge", "majority"]

JUDGE_MODEL = "openai/gpt-4.1-mini"


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


def judge(intent: str, script: str, *, model: str = JUDGE_MODEL, n: int = 3) -> bool | None:
    """Run the judge *n* times on whether *script* satisfies *intent*; majority-vote (D6)."""
    raise NotImplementedError(
        "the live LLM judge is not wired yet — the scaffold defines the judge surface and the "
        "majority vote; per-merge CI replays recorded verdicts"
    )
