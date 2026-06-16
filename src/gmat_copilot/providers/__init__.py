"""The model-agnostic provider abstraction (decisions D4, D7).

One thin :class:`Provider` protocol with four real adapters (Anthropic, OpenAI, Ollama, GitHub
Models) plus a :class:`RecordedProvider` that replays committed fixtures for deterministic,
zero-quota CI. There is **no default model**: selection is explicit (``"provider:model"``); with
none given, :func:`select` errors and lists the providers it can reach from configured credentials
— it never auto-picks or recommends one. Credentials come from the environment, never committed.

Each real adapter's ``complete`` performs the provider call through its optional extra
(``[anthropic]`` / ``[openai]`` / ``[ollama]``; GitHub Models needs none) and raises a clear,
actionable error when that extra is not installed or the credential is absent. The protocol,
credential discovery, no-default selection, and the recorded replay path round out the surface;
:class:`RecordingProvider` captures live completions into the fixture shape the recorded path
replays.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AnthropicProvider",
    "Completion",
    "GitHubModelsProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "Provider",
    "ProviderError",
    "RecordedProvider",
    "RecordingProvider",
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


_GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"


def _require(module: str, extra: str) -> Any:
    """Import an adapter's optional SDK, or raise a clear install hint if the extra is missing."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # the optional extra is not installed
        raise ProviderError(
            f"the {extra} provider needs an optional dependency that is not installed; "
            f"install it with: pip install 'gmat-copilot[{extra}]'"
        ) from exc


def _int_usage(values: Mapping[str, object]) -> dict[str, int]:
    """Keep only the integer token counts from a provider's native usage record."""
    return {key: value for key, value in values.items() if isinstance(value, int)}


def _field(obj: object, key: str, default: object = None) -> object:
    """Read *key* from a mapping or an object attribute — provider SDKs return either."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


class AnthropicProvider:
    """A Claude model via the user's ``ANTHROPIC_API_KEY`` (the ``[anthropic]`` extra)."""

    name = "anthropic"

    def reachable(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(
                "anthropic: no ANTHROPIC_API_KEY (the user supplies their own Claude key)"
            )
        anthropic = _require("anthropic", "anthropic")
        message = anthropic.Anthropic(api_key=key).messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        usage = _int_usage(
            {
                "input_tokens": getattr(message.usage, "input_tokens", None),
                "output_tokens": getattr(message.usage, "output_tokens", None),
            }
        )
        return Completion(text=text, provider=self.name, model=model, usage=usage)


class OpenAIProvider:
    """An OpenAI model with the user's key (``OPENAI_API_KEY``). Needs the ``[openai]`` extra."""

    name = "openai"

    def reachable(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("openai: no OPENAI_API_KEY")
        openai = _require("openai", "openai")
        response = openai.OpenAI(api_key=key).chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            provider=self.name,
            model=model,
            usage=_int_usage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
            )
            if usage is not None
            else {},
        )


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
        ollama = _require("ollama", "ollama")
        response = ollama.Client(host=self._host()).generate(
            model=model,
            prompt=prompt,
            options={"temperature": temperature, "num_predict": max_tokens},
        )
        raw = _field(response, "response", "")
        usage = _int_usage(
            {
                "prompt_eval_count": _field(response, "prompt_eval_count"),
                "eval_count": _field(response, "eval_count"),
            }
        )
        return Completion(
            text=raw if isinstance(raw, str) else "",
            provider=self.name,
            model=model,
            usage=usage,
        )


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
        token = self._token()
        if not token:
            raise ProviderError(
                "github: no token (set GH_TOKEN / MODELS_PAT or run `gh auth login`)"
            )
        body = json.dumps(
            {
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            _GITHUB_MODELS_ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        return Completion(
            text=payload["choices"][0]["message"]["content"],
            provider=self.name,
            model=model,
            usage=_int_usage(payload.get("usage", {})),
        )


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


class RecordingProvider:
    """Wraps a real provider and records every completion as a replayable fixture (D7 record mode).

    A drop-in :class:`Provider`: :meth:`complete` delegates to the wrapped provider and stores the
    result keyed by ``(provider, model, prompt)`` in the shape :class:`RecordedProvider` and the
    eval bundle replay. :meth:`save` writes the accumulated fixtures to disk, merging with any
    already there — the record mode that captures new fixtures for the deterministic CI path.
    """

    name = "recording"

    def __init__(self, inner: Provider):
        self.inner = inner
        self.fixtures: dict[str, dict[str, object]] = {}

    def reachable(self) -> bool:
        return self.inner.reachable()

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        completion = self.inner.complete(
            prompt, model=model, temperature=temperature, max_tokens=max_tokens
        )
        self.fixtures[prompt_key(completion.provider, model, prompt)] = {
            "text": completion.text,
            "usage": dict(completion.usage),
        }
        return completion

    def save(self, path: str | Path) -> Path:
        """Write the recorded fixtures to *path* as JSON, merging with any already present."""
        target = Path(path)
        merged: dict[str, object] = {}
        if target.exists():
            merged = json.loads(target.read_text(encoding="utf-8"))
        merged.update(self.fixtures)
        target.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


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
