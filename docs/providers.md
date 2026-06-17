# Providers & auth

Generation is **model-agnostic**. Every draft goes through one thin provider abstraction, and
**there is no default model** — you choose one explicitly. The choice is real: each provider needs
its own credential, so configuring one *is* the selection. With none chosen the tool lists the
providers it can reach rather than picking for you, and it never silently falls back to another.

## Selecting a model

A model is always named as `provider:model`:

```bash
gmat-copilot "a sun-synchronous orbit at 700 km" --model anthropic:claude-...
```

```python
from gmat_copilot import draft

draft("a sun-synchronous orbit at 700 km", model="anthropic:claude-...")
```

With no selector the tool errors and lists the providers reachable from your configured credentials:

```python
from gmat_copilot.providers import reachable_providers, select

reachable_providers()   # e.g. ["anthropic", "github"] — those with a credential present
select(None)            # raises ProviderError listing the reachable providers
```

## The providers

| Provider | Selector | Credential | Install |
| --- | --- | --- | --- |
| Anthropic | `anthropic:<model>` | `ANTHROPIC_API_KEY` | `gmat-copilot[anthropic]` |
| OpenAI | `openai:<model>` | `OPENAI_API_KEY` | `gmat-copilot[openai]` |
| Ollama | `ollama:<model>` | local server (`OLLAMA_HOST`, default `http://localhost:11434`) | `gmat-copilot[ollama]` |
| GitHub Models | `github:<owner/model>` | `GH_TOKEN` / `MODELS_PAT` / `GITHUB_TOKEN` | base install — no extra |

Credentials are read from the environment, never committed. An adapter with no credential still
resolves but reports `reachable() == False`, so a missing key surfaces as a clear error at call time
— it is never a quiet fallback to a different provider.

GitHub Models needs no provider SDK (it speaks the OpenAI-compatible HTTP API directly); it is the
free-tier path the [evaluation suite](evaluation.md) and CI use.

## The contract

Every adapter satisfies one `Provider` protocol:

```python
class Provider(Protocol):
    name: str
    def reachable(self) -> bool: ...
    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion: ...
```

`complete` returns a `Completion(text, provider, model, usage)`. Because the protocol is the whole
contract, adding a backend is just matching this shape — see [Add a provider](examples/add-a-provider.md).

## Deterministic CI

CI must be free and reproducible, so per-merge runs never call a live model. A `RecordedProvider`
replays committed fixtures keyed by `(provider, model, prompt)`, reporting `provider == "recorded"`;
a `RecordingProvider` captures live completions into that fixture shape. The
[evaluation suite](evaluation.md) builds on this to replay a frozen bundle with zero model calls and
zero quota.

See the [API reference](api.md) for the full provider surface.
