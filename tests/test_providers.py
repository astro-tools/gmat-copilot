"""The provider abstraction: no-default selection and deterministic recorded replay (D4/D7)."""

from __future__ import annotations

import pytest

from gmat_copilot.providers import (
    AnthropicProvider,
    Completion,
    ProviderError,
    RecordedProvider,
    prompt_key,
    reachable_providers,
    select,
)


def test_select_requires_explicit_model() -> None:
    with pytest.raises(ProviderError) as excinfo:
        select(None)
    assert "no model selected" in str(excinfo.value).lower()


def test_select_rejects_bare_model() -> None:
    with pytest.raises(ProviderError):
        select("claude-without-a-provider")


def test_select_rejects_unknown_provider() -> None:
    with pytest.raises(ProviderError):
        select("nope:some-model")


def test_select_resolves_known_provider() -> None:
    provider, model = select("anthropic:claude-x")
    assert provider.name == "anthropic"
    assert model == "claude-x"


def test_recorded_replays_deterministically() -> None:
    key = prompt_key("github", "m", "hello")
    fixtures = {key: {"text": "SCRIPT", "usage": {"total_tokens": 3}}}
    recorded = RecordedProvider(fixtures)

    first = recorded.complete("hello", model="m")
    second = recorded.complete("hello", model="m")

    assert isinstance(first, Completion)
    assert first.text == second.text == "SCRIPT"
    assert first.provider == "recorded"
    assert first.usage == {"total_tokens": 3}


def test_recorded_missing_fixture_errors() -> None:
    with pytest.raises(ProviderError):
        RecordedProvider({}).complete("never recorded", model="m")


def test_adapter_without_credential_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        AnthropicProvider().complete("draft a script", model="claude-x")


def test_reachable_providers_returns_list() -> None:
    assert isinstance(reachable_providers(), list)
