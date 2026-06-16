"""V4 spike proof: a model-agnostic Provider abstraction + recorded-vs-real determinism.

Defines one `Provider` protocol and four adapters behind it:

- `RecordedProvider`  — replays committed fixtures keyed by (provider, model, prompt). Deterministic.
- `GitHubModelsProvider` — real, OpenAI-compatible, via `gh auth token` / `MODELS_PAT`. Runnable.
- `AnthropicProvider`, `OllamaProvider` — interface-complete adapters for the user's own Claude
  key / a local Ollama. Not exercised here (no key / not installed); they raise a clear
  credential error when selected without one.

There is **no default model**: selection is explicit (`provider:model`). With no selection the
tool errors and lists the providers it can reach from configured credentials — it never picks or
recommends one. Settles D4 (protocol + adapters + auth) and D7 (CI inference path + budget).

Run::

    python v4_provider_proof.py                      # selection demo + record (gh token) + replay
    python v4_provider_proof.py --replay             # deterministic, no model calls

Deps: stdlib only. The GitHub Models adapter uses `gh auth token`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

HERE = Path(__file__).parent
FIXTURES = HERE / "v4_provider_fixtures.json"
GH_ENDPOINT = "https://models.github.ai/inference/chat/completions"

GEN_SYSTEM = ("You are a GMAT mission-script generator. Given a request, output ONLY a valid GMAT "
              ".script (resources, then BeginMissionSequence, then commands). No prose, no fences.")


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)


def _prompt_key(provider: str, model: str, prompt: str) -> str:
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    return f"{provider}:{model}:{h}"


class Provider(Protocol):
    name: str

    def reachable(self) -> bool: ...

    def complete(self, prompt: str, *, model: str, temperature: float = 0.0,
                 max_tokens: int = 1024) -> Completion: ...


class ProviderError(RuntimeError):
    pass


# ---------------- real adapters ----------------
def _gh_token() -> str:
    return (os.environ.get("GH_TOKEN") or os.environ.get("MODELS_PAT")
            or os.environ.get("GITHUB_TOKEN")
            or subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip())


class GitHubModelsProvider:
    name = "github"

    def reachable(self) -> bool:
        return bool(_gh_token())

    def complete(self, prompt, *, model, temperature=0.0, max_tokens=1024) -> Completion:
        token = _gh_token()
        if not token:
            raise ProviderError("github: no token (set GH_TOKEN / MODELS_PAT or `gh auth login`)")
        body = json.dumps({"model": model, "temperature": temperature, "max_tokens": max_tokens,
                           "messages": [{"role": "system", "content": GEN_SYSTEM},
                                        {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(GH_ENDPOINT, data=body, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        return Completion(text=d["choices"][0]["message"]["content"], provider=self.name,
                          model=model, usage=d.get("usage", {}))


class AnthropicProvider:
    name = "anthropic"

    def reachable(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, prompt, *, model, temperature=0.0, max_tokens=1024) -> Completion:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("anthropic: no ANTHROPIC_API_KEY (the user supplies their own Claude key)")
        body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": temperature,
                           "system": GEN_SYSTEM,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        return Completion(text="".join(b.get("text", "") for b in d.get("content", [])),
                          provider=self.name, model=model, usage=d.get("usage", {}))


class OllamaProvider:
    name = "ollama"

    def _host(self) -> str:
        return os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def reachable(self) -> bool:
        try:
            with urllib.request.urlopen(self._host() + "/api/tags", timeout=2):
                return True
        except Exception:
            return False

    def complete(self, prompt, *, model, temperature=0.0, max_tokens=1024) -> Completion:
        if not self.reachable():
            raise ProviderError(f"ollama: not reachable at {self._host()} (start `ollama serve`)")
        body = json.dumps({"model": model, "system": GEN_SYSTEM, "prompt": prompt, "stream": False,
                           "options": {"temperature": temperature, "num_predict": max_tokens}}).encode()
        with urllib.request.urlopen(self._host() + "/api/generate", data=body, timeout=120) as r:
            d = json.load(r)
        return Completion(text=d.get("response", ""), provider=self.name, model=model)


# ---------------- recorded adapter ----------------
class RecordedProvider:
    name = "recorded"

    def __init__(self, fixtures: dict):
        self.fixtures = fixtures

    def reachable(self) -> bool:
        return True

    def complete(self, prompt, *, model, temperature=0.0, max_tokens=1024) -> Completion:
        # the recorded provider replays whatever provider produced the fixture
        for prov in ("github", "anthropic", "ollama"):
            key = _prompt_key(prov, model, prompt)
            if key in self.fixtures:
                f = self.fixtures[key]
                return Completion(text=f["text"], provider="recorded", model=model, usage=f.get("usage", {}))
        raise ProviderError(f"recorded: no fixture for model={model!r} prompt-hash; record it first")


# ---------------- registry + no-default selection ----------------
REAL = {p.name: p for p in (GitHubModelsProvider(), AnthropicProvider(), OllamaProvider())}


def reachable_providers() -> list[str]:
    return [name for name, p in REAL.items() if p.reachable()]


def select(model_str: str | None):
    """No default: explicit 'provider:model' required; otherwise error + list reachable."""
    if not model_str:
        raise ProviderError(
            "no model selected — pass provider:model (e.g. anthropic:claude-..., github:openai/gpt-4.1-mini, "
            f"ollama:llama3). Reachable now: {reachable_providers() or 'none (configure a credential)'}")
    if ":" not in model_str:
        raise ProviderError(f"model must be 'provider:model', got {model_str!r}")
    prov, model = model_str.split(":", 1)
    if prov not in REAL:
        raise ProviderError(f"unknown provider {prov!r}; known: {sorted(REAL)}")
    return REAL[prov], model


# ---------------- proof ----------------
DEMO_PROMPTS = [
    "A 500 km circular Earth orbit at 51.6 deg inclination; propagate one day; report altitude and SMA.",
    "Raise the apogee of a 500 km circular LEO with one prograde impulsive burn.",
]


def selection_demo():
    print("=== no-default selection ===")
    print(f"  reachable providers (from credentials): {reachable_providers()}")
    for arg in (None, "openai/gpt-4.1-mini", "anthropic:claude-sonnet", "github:openai/gpt-4.1-mini"):
        try:
            p, m = select(arg)
            print(f"  select({arg!r:34}) -> provider={p.name} model={m} reachable={p.reachable()}")
        except ProviderError as e:
            print(f"  select({arg!r:34}) -> ERROR: {str(e)[:88]}")


def main():
    ap = argparse.ArgumentParser(description="V4 provider-abstraction proof.")
    ap.add_argument("--replay", action="store_true", help="replay fixtures only (no model calls)")
    ap.add_argument("--record-model", default="github:openai/gpt-4.1-mini")
    args = ap.parse_args()

    selection_demo()

    if args.replay or not REAL["github"].reachable():
        if not FIXTURES.exists():
            sys.exit("no fixtures to replay; run a live record first")
        fixtures = json.loads(FIXTURES.read_text())
    else:
        # record live via the chosen real provider
        prov, model = select(args.record_model)
        fixtures = json.loads(FIXTURES.read_text()) if FIXTURES.exists() else {}
        print(f"\n=== record (live) via {prov.name}:{model} ===")
        for pr in DEMO_PROMPTS:
            c = prov.complete(pr, model=model, temperature=0, max_tokens=900)
            fixtures[_prompt_key(prov.name, model, pr)] = {"text": c.text, "usage": c.usage}
            print(f"  recorded {len(c.text)} chars for: {pr[:48]}...")
        FIXTURES.write_text(json.dumps(fixtures, indent=2))

    # determinism: RecordedProvider replays byte-identically twice
    print("\n=== determinism over the recorded path ===")
    rec = RecordedProvider(fixtures)
    model = args.record_model.split(":", 1)[1]
    ok = True
    for pr in DEMO_PROMPTS:
        a = rec.complete(pr, model=model)
        b = rec.complete(pr, model=model)
        same = a.text == b.text
        ok = ok and same
        print(f"  replay==replay: {same}  ({len(a.text)} chars)  {pr[:44]}...")
    # cross-run determinism via a fresh RecordedProvider from the same fixtures
    rec2 = RecordedProvider(json.loads(FIXTURES.read_text()) if FIXTURES.exists() else fixtures)
    cross = all(rec.complete(pr, model=model).text == rec2.complete(pr, model=model).text
                for pr in DEMO_PROMPTS)
    print(f"  byte-identical across fresh RecordedProvider instances: {cross}")
    print(f"\nRESULT: recorded path deterministic = {ok and cross}")


if __name__ == "__main__":
    main()
