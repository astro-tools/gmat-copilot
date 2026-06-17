"""The LLM judge: verdict parsing, the majority vote, and the n-shot judge (decision D6).

The live model call is exercised through an injected :class:`Provider` stand-in, so these tests run
offline and deterministically — no GitHub Models call, no quota.
"""

from __future__ import annotations

import pytest

from gmat_copilot.eval import judge, judge_verdicts, majority, parse_verdict
from gmat_copilot.eval.judge import JUDGE_SYSTEM
from gmat_copilot.providers import Completion


class CannedJudge:
    """A :class:`~gmat_copilot.providers.Provider` that returns canned verdict texts in order."""

    name = "canned"

    def __init__(self, texts: list[str]) -> None:
        self._texts = texts
        self.prompts: list[str] = []

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        self.prompts.append(prompt)
        text = self._texts[len(self.prompts) - 1]
        return Completion(text=text, provider=self.name, model=model)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"satisfies_intent": true, "reason": "ok"}', True),
        ('{"satisfies_intent": false, "reason": "wrong orbit"}', False),
        ('here is my answer: {"satisfies_intent": true} done', True),
        ("The script satisfies the intent: true.", True),
        ("This is false — wrong inclination.", False),
        ('{"satisfies_intent": "yes"}', None),  # not a bool, and prose has no clean true/false
        ("maybe, it is both true and false at once", None),  # ambiguous
        ("[true]", True),  # not a dict, but prose fallback finds an unambiguous 'true'
        ("¯\\_(ツ)_/¯", None),  # unreadable -> None, dropped by majority
    ],
)
def test_parse_verdict(content: str, expected: bool | None) -> None:
    assert parse_verdict(content) is expected


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ([True, True, False], True),
        ([False, False, True], False),
        ([True, False], False),  # tie -> FAIL (decision D6)
        ([True, None, None], True),  # None is dropped, not a vote
        ([None, None], None),  # no real votes
        ([], None),
        ([True], True),
    ],
)
def test_majority(verdicts: list[bool | None], expected: bool | None) -> None:
    assert majority(verdicts) is expected


def test_judge_verdicts_collects_each_run() -> None:
    provider = CannedJudge(
        [
            '{"satisfies_intent": true}',
            '{"satisfies_intent": false}',
            '{"satisfies_intent": true}',
        ]
    )
    verdicts = judge_verdicts("the intent", "the script", provider=provider, n=3)
    assert verdicts == [True, False, True]
    assert len(provider.prompts) == 3


def test_judge_returns_the_majority() -> None:
    provider = CannedJudge(['{"satisfies_intent": true}'] * 2 + ['{"satisfies_intent": false}'])
    assert judge("intent", "script", provider=provider, n=3) is True


def test_judge_fails_a_tie() -> None:
    provider = CannedJudge(['{"satisfies_intent": true}', '{"satisfies_intent": false}'])
    assert judge("intent", "script", provider=provider, n=2) is False


def test_judge_prompt_carries_the_rubric_intent_and_script() -> None:
    provider = CannedJudge(['{"satisfies_intent": true}'])
    judge_verdicts("ORBIT IS GEO", "Create Spacecraft Sat;", provider=provider, n=1)
    prompt = provider.prompts[0]
    assert JUDGE_SYSTEM in prompt
    assert "ORBIT IS GEO" in prompt
    assert "Create Spacecraft Sat;" in prompt


def test_pace_sleeps_between_calls_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    provider = CannedJudge(['{"satisfies_intent": true}'] * 3)
    judge_verdicts("i", "s", provider=provider, n=3, pace=1.5)
    assert sleeps == [1.5, 1.5]  # n-1 sleeps, none before the first call


def test_default_provider_is_github_models(monkeypatch: pytest.MonkeyPatch) -> None:
    # With no provider injected, the judge reaches for GitHubModelsProvider (free-tier path, D7).
    # Resolve the submodule via importlib — the re-exported ``judge`` function shadows it on the
    # package, so ``import gmat_copilot.eval.judge as m`` would bind the function, not the module.
    import importlib

    judge_module = importlib.import_module("gmat_copilot.eval.judge")
    canned = CannedJudge(['{"satisfies_intent": true}'])
    monkeypatch.setattr(judge_module, "GitHubModelsProvider", lambda: canned)
    assert judge_verdicts("i", "s", n=1) == [True]
