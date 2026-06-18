"""The evaluation suite: prompt set, structural scorer, LLM judge, and scorer (D6/D7)."""

from __future__ import annotations

from .judge import JUDGE_MODEL, JUDGE_SYSTEM, judge, judge_verdicts, majority, parse_verdict
from .lift import (
    DraftScore,
    LiftReport,
    LiftRow,
    RecordedDryRun,
    run_live_lift,
    run_recorded_lift,
)
from .prompts import EvalPrompt, StructuralSpec, load_prompts
from .runner import EvalReport, PromptOutcome, record_bundle, run_live, run_recorded
from .scorer import StructuralResult, structural_score

__all__ = [
    "JUDGE_MODEL",
    "JUDGE_SYSTEM",
    "DraftScore",
    "EvalPrompt",
    "EvalReport",
    "LiftReport",
    "LiftRow",
    "PromptOutcome",
    "RecordedDryRun",
    "StructuralResult",
    "StructuralSpec",
    "judge",
    "judge_verdicts",
    "load_prompts",
    "majority",
    "parse_verdict",
    "record_bundle",
    "run_live",
    "run_live_lift",
    "run_recorded",
    "run_recorded_lift",
    "structural_score",
]
