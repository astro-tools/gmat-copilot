"""The provider abstraction: no-default selection and deterministic recorded replay (D4/D7)."""

from __future__ import annotations

import importlib
import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from gmat_copilot.providers import (
    AnthropicProvider,
    Completion,
    GitHubModelsProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderError,
    RecordedProvider,
    RecordingProvider,
    prompt_key,
    reachable_providers,
    select,
)


def _patch_import(monkeypatch: pytest.MonkeyPatch, name: str, module: object) -> None:
    """Return *module* from ``import_module(name)``; let every other import pass through."""
    real = importlib.import_module

    def fake(target: str, package: str | None = None) -> object:
        return module if target == name else real(target, package)

    monkeypatch.setattr(importlib, "import_module", fake)


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


def test_missing_extra_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    real = importlib.import_module

    def fake(target: str, package: str | None = None) -> object:
        if target == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real(target, package)

    monkeypatch.setattr(importlib, "import_module", fake)
    with pytest.raises(ProviderError) as excinfo:
        AnthropicProvider().complete("draft", model="claude-x")
    assert "gmat-copilot[anthropic]" in str(excinfo.value)


def test_anthropic_complete_shapes_request_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    captured: dict[str, object] = {}

    class Messages:
        def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="SCRIPT")],
                usage=SimpleNamespace(input_tokens=11, output_tokens=22),
            )

    class Anthropic:
        def __init__(self, *, api_key: str) -> None:
            captured["api_key"] = api_key
            self.messages = Messages()

    _patch_import(monkeypatch, "anthropic", SimpleNamespace(Anthropic=Anthropic))
    completion = AnthropicProvider().complete("draft", model="claude-x", max_tokens=128)

    assert completion.text == "SCRIPT"
    assert completion.provider == "anthropic"
    assert completion.model == "claude-x"
    assert completion.usage == {"input_tokens": 11, "output_tokens": 22}
    assert captured["api_key"] == "sk-test"
    assert captured["model"] == "claude-x"
    assert captured["max_tokens"] == 128
    assert captured["messages"] == [{"role": "user", "content": "draft"}]


def test_openai_complete_shapes_request_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict[str, object] = {}

    class Completions:
        def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="SCRIPT"))],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7),
            )

    class OpenAI:
        def __init__(self, *, api_key: str) -> None:
            captured["api_key"] = api_key
            self.chat = SimpleNamespace(completions=Completions())

    _patch_import(monkeypatch, "openai", SimpleNamespace(OpenAI=OpenAI))
    completion = OpenAIProvider().complete("draft", model="gpt-x")

    assert completion.text == "SCRIPT"
    assert completion.provider == "openai"
    assert completion.usage == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert captured["model"] == "gpt-x"
    assert captured["messages"] == [{"role": "user", "content": "draft"}]


def test_ollama_complete_shapes_request_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OllamaProvider, "reachable", lambda self: True)
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, *, host: str) -> None:
            captured["host"] = host

        def generate(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return {"response": "SCRIPT", "prompt_eval_count": 5, "eval_count": 9}

    _patch_import(monkeypatch, "ollama", SimpleNamespace(Client=Client))
    completion = OllamaProvider().complete("draft", model="llama3", temperature=0.2, max_tokens=64)

    assert completion.text == "SCRIPT"
    assert completion.provider == "ollama"
    assert completion.usage == {"prompt_eval_count": 5, "eval_count": 9}
    assert captured["model"] == "llama3"
    assert captured["prompt"] == "draft"
    assert captured["options"] == {"temperature": 0.2, "num_predict": 64}


def test_github_complete_shapes_request_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "ght")
    captured: dict[str, object] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": "SCRIPT"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                }
            ).encode("utf-8")

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> FakeResponse:
        body = request.data
        assert isinstance(body, bytes)
        captured["url"] = request.full_url
        captured["body"] = json.loads(body.decode("utf-8"))
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    completion = GitHubModelsProvider().complete("draft", model="openai/gpt-4.1-mini")

    assert completion.text == "SCRIPT"
    assert completion.provider == "github"
    assert completion.usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    assert captured["url"] == "https://models.github.ai/inference/chat/completions"
    assert captured["auth"] == "Bearer ght"
    assert captured["body"] == {
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.0,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "draft"}],
    }


class _FakeProvider:
    """A stand-in real provider that reports a real provider name in its completions."""

    name = "github"

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        return Completion(text="SCRIPT", provider="github", model=model, usage={"total_tokens": 5})


def test_recording_provider_captures_and_round_trips(tmp_path: Path) -> None:
    out_path = tmp_path / "fixtures.json"
    out_path.write_text(json.dumps({"github:other:deadbeef": {"text": "OLD", "usage": {}}}))

    recorder = RecordingProvider(_FakeProvider())
    completion = recorder.complete("hi", model="m")

    assert completion.provider == "github"
    key = prompt_key("github", "m", "hi")
    assert recorder.fixtures[key] == {"text": "SCRIPT", "usage": {"total_tokens": 5}}

    recorder.save(out_path)
    saved = json.loads(out_path.read_text())
    assert saved["github:other:deadbeef"]["text"] == "OLD"  # merged, not clobbered
    assert saved[key]["text"] == "SCRIPT"

    replay = RecordedProvider(saved).complete("hi", model="m")
    assert replay.text == "SCRIPT"
    assert replay.provider == "recorded"
