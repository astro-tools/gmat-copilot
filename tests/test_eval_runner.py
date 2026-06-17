"""The eval runner: recorded replay, the live path, and the record/replay round-trip (D6/D7).

The recorded path is pure. The live path is exercised with an injected generation provider +
retriever (so the real ``draft`` orchestration runs offline) and an injected judge provider, so no
test touches the network or the FAISS index.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gmat_copilot.eval import EvalReport, load_prompts, record_bundle, run_live, run_recorded
from gmat_copilot.eval.judge import JUDGE_MODEL
from gmat_copilot.providers import Completion
from gmat_copilot.rag import Retriever
from gmat_copilot.result import RetrievalTrace

MODEL = "openai/gpt-4.1-mini"

# A lint-clean script that satisfies a Spacecraft+Propagator+ReportFile / Propagate+Report spec.
GOOD_SCRIPT = """Create Spacecraft Sat;
Sat.SMA = 6878;
Sat.ECC = 0;
Sat.INC = 51.6;
Create ForceModel FM;
Create Propagator Prop;
Prop.FM = FM;
Create ReportFile rf;
rf.Add = {Sat.Earth.Altitude};
BeginMissionSequence;
Propagate Prop(Sat) {Sat.ElapsedDays = 1};
Report rf Sat.Earth.Altitude;
"""


class StubRetriever(Retriever):
    """An empty-trace retriever — keeps ``draft`` off the FAISS index."""

    def __init__(self) -> None:
        super().__init__()

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        return RetrievalTrace()


class StubGen:
    """A generation provider stand-in named ``github`` so recorded keys resolve on replay."""

    name = "github"

    def __init__(self, script: str) -> None:
        self._script = script

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        return Completion(text=self._script, provider=self.name, model=model)


class CannedJudge:
    """Returns a fixed verdict text for every call."""

    name = "canned"

    def __init__(self, text: str) -> None:
        self._text = text

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        return Completion(text=self._text, provider=self.name, model=model)


def _write_bundle(
    directory: Path,
    prompts: list[dict[str, Any]],
    completions: dict[str, Any],
    judge: dict[str, Any],
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "prompts.json").write_text(json.dumps(prompts), encoding="utf-8")
    (directory / "completions.json").write_text(json.dumps(completions), encoding="utf-8")
    (directory / "judge.json").write_text(json.dumps(judge), encoding="utf-8")
    return directory


def _key(prompt: dict[str, Any]) -> str:
    from gmat_copilot.providers import prompt_key

    return prompt_key("github", MODEL, prompt["request"])


def test_empty_report_has_zero_pass_rate() -> None:
    report = EvalReport()
    assert report.pass_rate == 0.0
    assert report.pass_rate_by_tier == {}


def test_recorded_replay_is_deterministic_and_aggregates_by_tier(tmp_path: Path) -> None:
    prompts = [
        {
            "id": "p_easy",
            "difficulty": "easy",
            "request": "an easy one",
            "intent": "easy intent",
            "structural": {
                "required_types": ["Spacecraft", "Propagator", "ReportFile"],
                "required_commands": ["Propagate", "Report"],
            },
        },
        {
            "id": "p_medium",
            "difficulty": "medium",
            "request": "a medium one",
            "intent": "medium intent",
            "structural": {"required_types": ["Spacecraft"]},
        },
    ]
    completions = {_key(p): {"text": GOOD_SCRIPT, "usage": {}} for p in prompts}
    judge = {MODEL: {"p_easy": [True, True, True], "p_medium": [True, False, True]}}
    bundle = _write_bundle(tmp_path / "b", prompts, completions, judge)

    first = run_recorded(bundle, model=MODEL)
    second = run_recorded(bundle, model=MODEL)
    assert first == second
    assert first.pass_rate == 1.0
    assert first.pass_rate_by_tier == {"easy": 1.0, "medium": 1.0}


def test_negative_control_lint_clean_but_intent_wrong_fails(tmp_path: Path) -> None:
    # The script lints clean and meets every structural assertion, but the judge says it ignores the
    # intent -> the prompt FAILS. This is the D6 negative control: structural alone would wave it
    # through; the judge layer is what catches the semantic miss.
    prompts = [
        {
            "id": "neg",
            "difficulty": "easy",
            "request": "a 500 km LEO at 51.6 deg",
            "intent": "a 500 km LEO at 51.6 deg inclination",
            "structural": {
                "required_types": ["Spacecraft", "Propagator", "ReportFile"],
                "required_commands": ["Propagate", "Report"],
            },
        }
    ]
    completions = {_key(prompts[0]): {"text": GOOD_SCRIPT, "usage": {}}}
    judge = {MODEL: {"neg": [False, False, False]}}
    bundle = _write_bundle(tmp_path / "neg", prompts, completions, judge)

    report = run_recorded(bundle, model=MODEL)
    outcome = report.outcomes[0]
    assert outcome.structural.passed  # structurally clean...
    assert outcome.judge is False  # ...but the judge rejects the intent...
    assert not outcome.passed  # ...so the prompt fails.
    assert report.pass_rate == 0.0


def test_recorded_accepts_an_unmodeled_judge_file(tmp_path: Path) -> None:
    # judge.json may omit the model layer ({prompt_id: [...]}); the replay falls back to it.
    prompts = [
        {
            "id": "p",
            "difficulty": "easy",
            "request": "x",
            "intent": "y",
            "structural": {"required_types": ["Spacecraft"]},
        }
    ]
    completions = {_key(prompts[0]): {"text": GOOD_SCRIPT, "usage": {}}}
    bundle = _write_bundle(tmp_path / "u", prompts, completions, {"p": [True, True, True]})

    outcome = run_recorded(bundle, model=MODEL).outcomes[0]
    assert outcome.judge is True
    assert outcome.passed


def test_run_live_paces_between_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    prompts = load_prompts(
        _write_bundle(
            tmp_path / "paced",
            [
                {
                    "id": "a",
                    "difficulty": "easy",
                    "request": "r1",
                    "intent": "i1",
                    "structural": {},
                },
                {
                    "id": "b",
                    "difficulty": "easy",
                    "request": "r2",
                    "intent": "i2",
                    "structural": {},
                },
            ],
            {},
            {},
        )
        / "prompts.json"
    )
    report = run_live(
        prompts,
        model=MODEL,
        provider=StubGen(GOOD_SCRIPT),
        retriever=StubRetriever(),
        judge_provider=CannedJudge('{"satisfies_intent": true}'),
        n=1,
        pace=2.0,
    )
    assert len(report.outcomes) == 2


def test_missing_verdicts_yield_a_none_judge(tmp_path: Path) -> None:
    prompts = [
        {
            "id": "p",
            "difficulty": "easy",
            "request": "x",
            "intent": "y",
            "structural": {"required_types": ["Spacecraft"]},
        }
    ]
    completions = {_key(prompts[0]): {"text": GOOD_SCRIPT, "usage": {}}}
    bundle = _write_bundle(tmp_path / "m", prompts, completions, {MODEL: {}})

    outcome = run_recorded(bundle, model=MODEL).outcomes[0]
    assert outcome.judge is None
    assert not outcome.passed


def test_run_live_scores_each_prompt(tmp_path: Path) -> None:
    prompts = load_prompts(
        _write_bundle(
            tmp_path / "live",
            [
                {
                    "id": "p",
                    "difficulty": "easy",
                    "request": "a LEO",
                    "intent": "a LEO",
                    "structural": {
                        "required_types": ["Spacecraft", "Propagator", "ReportFile"],
                        "required_commands": ["Propagate", "Report"],
                    },
                }
            ],
            {},
            {},
        )
        / "prompts.json"
    )
    report = run_live(
        prompts,
        model=MODEL,
        provider=StubGen(GOOD_SCRIPT),
        retriever=StubRetriever(),
        judge_provider=CannedJudge('{"satisfies_intent": true}'),
        n=3,
    )
    assert report.pass_rate == 1.0
    assert report.outcomes[0].judge is True


def test_record_then_replay_reproduces_the_live_report(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "rt",
        [
            {
                "id": "p",
                "difficulty": "easy",
                "request": "a LEO",
                "intent": "a LEO",
                "structural": {
                    "required_types": ["Spacecraft", "Propagator", "ReportFile"],
                    "required_commands": ["Propagate", "Report"],
                },
            }
        ],
        {},
        {},
    )
    prompts = load_prompts(bundle / "prompts.json")

    live = record_bundle(
        prompts,
        bundle,
        model=MODEL,
        provider=StubGen(GOOD_SCRIPT),
        retriever=StubRetriever(),
        judge_provider=CannedJudge('{"satisfies_intent": true}'),
        n=3,
    )
    # The frozen fixtures exist and replay to the same report the live run produced.
    assert (bundle / "completions.json").exists()
    assert (bundle / "judge.json").exists()
    replayed = run_recorded(bundle, model=MODEL)
    assert replayed == live
    assert replayed.pass_rate == 1.0
    # judge.json is keyed by the judge model, prompt id -> the raw N verdicts.
    recorded_judge = json.loads((bundle / "judge.json").read_text("utf-8"))
    assert recorded_judge[JUDGE_MODEL]["p"] == [True, True, True]
