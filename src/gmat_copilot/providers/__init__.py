"""The model-agnostic provider abstraction (decisions D4, D7).

One thin :class:`Provider` protocol with four real adapters (Anthropic, OpenAI, Ollama, GitHub
Models) plus a :class:`RecordedProvider` that replays committed fixtures for deterministic,
zero-quota CI. There is **no default model**: selection is explicit (``"provider:model"``); with
none given, :func:`select` errors and lists the providers it can reach from configured credentials
— it never auto-picks or recommends one. Credentials come from the environment, never committed.

The real adapters' ``complete`` calls are wired by the generation feature work; the protocol,
credential discovery, no-default selection, and the recorded replay path are established here.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "AnthropicProvider",
    "Completion",
    "GitHubModelsProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "Provider",
    "ProviderError",
    "RecordedProvider",
    "reachable_providers",
    "select",
]


@dataclass(frozen=True, slots=True)
class Completion:
    """A single provider completion: the text plus the provider/model/usage that produced it."""

    text: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """A provider could not satisfy a request (missing credential, unreachable, or unknown)."""


@runtime_checkable
class Provider(Protocol):
    """The contract every adapter satisfies."""

    name: str

    def reachable(self) -> bool:
        """Whether a call could succeed now — i.e. a credential/host is configured."""
        ...

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        """Generate a completion for *prompt* with *model*."""
        ...


def prompt_key(provider: str, model: str, prompt: str) -> str:
    """The deterministic fixture key for a ``(provider, model, prompt)`` triple."""
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    return f"{provider}:{model}:{digest}"


def _not_wired(provider: str) -> ProviderError:
    return ProviderError(
        f"{provider}: live generation is not wired yet; the scaffold establishes the provider "
        "surface. The API call lands with the generation work"
    )


class AnthropicProvider:
    """A Claude model via the user's ``ANTHROPIC_API_KEY`` (the ``[anthropic]`` extra)."""

    name = "anthropic"

    def reachable(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        if not self.reachable():
            raise ProviderError(
                "anthropic: no ANTHROPIC_API_KEY (the user supplies their own Claude key)"
            )
        raise _not_wired(self.name)


class OpenAIProvider:
    """An OpenAI model with the user's key (``OPENAI_API_KEY``). Needs the ``[openai]`` extra."""

    name = "openai"

    def reachable(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        if not self.reachable():
            raise ProviderError("openai: no OPENAI_API_KEY")
        raise _not_wired(self.name)


class OllamaProvider:
    """A local Ollama server (``OLLAMA_HOST``, default ``http://localhost:11434``)."""

    name = "ollama"

    def _host(self) -> str:
        return os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def reachable(self) -> bool:
        try:
            with urllib.request.urlopen(self._host() + "/api/tags", timeout=2):
                return True
        except Exception:
            return False

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        if not self.reachable():
            raise ProviderError(f"ollama: not reachable at {self._host()} (start `ollama serve`)")
        raise _not_wired(self.name)


class GitHubModelsProvider:
    """GitHub Models (OpenAI-compatible), authenticated with ``GH_TOKEN`` / ``MODELS_PAT``.

    The free-tier path the eval and CI use; no provider SDK required.
    """

    name = "github"

    def _token(self) -> str:
        return (
            os.environ.get("GH_TOKEN")
            or os.environ.get("MODELS_PAT")
            or os.environ.get("GITHUB_TOKEN")
            or ""
        )

    def reachable(self) -> bool:
        return bool(self._token())

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        if not self.reachable():
            raise ProviderError(
                "github: no token (set GH_TOKEN / MODELS_PAT or run `gh auth login`)"
            )
        raise _not_wired(self.name)


class RecordedProvider:
    """Replays committed fixtures keyed by ``(provider, model, prompt)`` — fully deterministic.

    The CI inference path (decision D7): zero model calls, zero quota. A fixture records whatever
    real provider produced it; the replay reports ``provider == "recorded"``.
    """

    name = "recorded"
    _SOURCES = ("github", "anthropic", "openai", "ollama")

    def __init__(self, fixtures: Mapping[str, Mapping[str, object]]):
        self.fixtures = fixtures

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        for source in self._SOURCES:
            entry = self.fixtures.get(prompt_key(source, model, prompt))
            if entry is not None:
                text = entry.get("text", "")
                usage = entry.get("usage", {})
                return Completion(
                    text=text if isinstance(text, str) else "",
                    provider=self.name,
                    model=model,
                    usage=usage if isinstance(usage, dict) else {},
                )
        raise ProviderError(
            f"recorded: no fixture for model={model!r} and this prompt; record it first"
        )


# The credential-gated real adapters, by name. RecordedProvider is constructed explicitly with
# fixtures, so it is not credential-selectable here.
_REGISTRY: dict[str, Provider] = {
    p.name: p
    for p in (AnthropicProvider(), OpenAIProvider(), OllamaProvider(), GitHubModelsProvider())
}


def reachable_providers() -> list[str]:
    """The real providers reachable now from configured credentials, in registry order."""
    return [name for name, provider in _REGISTRY.items() if provider.reachable()]


def select(spec: str | None) -> tuple[Provider, str]:
    """Resolve a ``"provider:model"`` *spec* to a ``(provider, model)`` pair — no default (D4).

    :raises ProviderError: if *spec* is missing (lists the reachable providers), malformed, or
        names an unknown provider.
    """
    if not spec:
        reachable = reachable_providers()
        raise ProviderError(
            "no model selected - pass provider:model (e.g. anthropic:claude-..., "
            "github:openai/gpt-4.1-mini, ollama:llama3). "
            f"Reachable now: {reachable or 'none (configure a credential)'}"
        )
    if ":" not in spec:
        raise ProviderError(f"model must be 'provider:model', got {spec!r}")
    name, model = spec.split(":", 1)
    if name not in _REGISTRY:
        raise ProviderError(f"unknown provider {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name], model
