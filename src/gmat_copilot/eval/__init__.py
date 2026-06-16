"""The evaluation suite: prompt set, structural scorer, LLM judge, and scorer (D6/D7)."""

from __future__ import annotations

from .judge import JUDGE_MODEL, judge, majority
from .prompts import EvalPrompt, StructuralSpec, load_prompts
from .runner import EvalReport, PromptOutcome, run_recorded
from .scorer import StructuralResult, structural_score

__all__ = [
    "JUDGE_MODEL",
    "EvalPrompt",
    "EvalReport",
    "PromptOutcome",
    "StructuralResult",
    "StructuralSpec",
    "judge",
    "load_prompts",
    "majority",
    "run_recorded",
    "structural_score",
]
