# V4 — provider abstraction + CI inference budget & determinism

**Spike question.** Confirm one `Provider` abstraction spans a hosted Claude model, OpenAI, and
local Ollama plus a recorded provider; pin the CI-time inference path so the pipeline is testable
without paid, flaky inference; prove the recorded path is deterministic. Feeds the design freeze
as **D4** (provider abstraction + adapters + auth) and **D7** (CI inference path + budget).

## Recommendation (TL;DR)

- **One thin `Provider` protocol** — `complete(prompt, *, model, temperature, max_tokens) ->
  Completion(text, provider, model, usage)` + `reachable()`. Four adapters satisfy it:
  `GitHubModelsProvider` (OpenAI-compatible, free tier), `AnthropicProvider` (the user's own Claude
  key), `OllamaProvider` (local), and `RecordedProvider` (replays fixtures).
- **No default model (D4).** Selection is explicit — `provider:model`. With no selection the tool
  **errors and lists the providers it can reach** from configured credentials; it never auto-picks
  or recommends one. *This supersedes the charter's "default to a current Claude model" language.*
- **Per-merge CI uses the `RecordedProvider` (D7)** — deterministic, zero model calls, zero quota
  (proven byte-identical replay). **Real** GitHub-Models runs only on `workflow_dispatch` /
  fixture-refresh; budget = the free Low-tier (150/day, `gpt-4.1-mini` — the V3 judge model); CI
  needs a personal `MODELS_PAT` (the workflow `GITHUB_TOKEN` is unreliable for inference). The
  recorded path removes the per-PR live call entirely, so the "per-PR subset vs full suite" split
  collapses to **recorded-per-PR vs live-on-dispatch**.

## D4 — provider abstraction + auth

- **Protocol:** `complete(...) -> Completion` + `reachable()`. The four adapters differ only in
  transport/auth; the pipeline holds a `Provider`, not a vendor SDK.
- **No default / explicit selection.** `select("provider:model")` resolves the adapter; `select(None)`
  raises with the reachable-provider list; a bare model string (no `provider:`) is rejected. An
  adapter with no credential resolves but reports `reachable() == False`, so a missing key surfaces
  as a clear error at call time — never a silent fallback to another provider.
- **Auth** — credentials come from the environment, never committed: `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `gh auth token` / `MODELS_PAT` (GitHub Models), `OLLAMA_HOST`. Each adapter
  discovers its own via `reachable()`.
- **Reach in this environment:** only `github` is live (no Anthropic/OpenAI key, no Ollama), so the
  Anthropic and Ollama adapters are *interface-validated* (they resolve and correctly report
  unreachable), not live-exercised. The GitHub Models adapter is exercised for real.

## D7 — CI inference path + budget

- **Per-merge (every PR):** the eval (generation + judge) runs against **recorded fixtures** — the
  `RecordedProvider` for generation (this spike) and the recorded judge verdicts (V3). Recorded
  generation → fixed candidate → recorded judge verdict → **fixed score**, with **no live model and
  no quota**, byte-identical across runs and platforms.
- **Live runs (`workflow_dispatch` / fixture-refresh / leaderboard):** real GitHub Models,
  `gpt-4.1-mini`, free Low-tier **150/day**; CI authenticates with a personal `MODELS_PAT`. Locally,
  `gh auth token` works directly.
- **The per-PR-subset question dissolves.** Because per-PR is recorded (zero live calls), there is no
  per-PR inference budget to subset — the split is simply recorded-per-PR vs live-full-on-dispatch.

## Results

```
=== no-default selection ===
  reachable providers (from credentials): ['github']
  select(None)                         -> ERROR: no model selected — pass provider:model ...
  select('openai/gpt-4.1-mini')        -> ERROR: model must be 'provider:model'
  select('anthropic:claude-sonnet')    -> provider=anthropic reachable=False   (no key -> errors at call)
  select('github:openai/gpt-4.1-mini') -> provider=github   reachable=True
=== determinism over the recorded path ===
  replay==replay: True (both prompts); byte-identical across fresh RecordedProvider instances: True
  RESULT: recorded path deterministic = True
```

## Findings

1. **No default is clean and sufficient.** Every provider needs its own credential, so configuring
   one *is* the choice; the tool requires `provider:model` and lists reachable providers when it's
   omitted. Unreachable adapters resolve but fail at call with a credential error — no silent
   vendor fallback. (This is the agreed correction to the charter's Claude-default language.)
2. **The recorded path is byte-deterministic** — the property the whole per-merge CI relies on. With
   the V3 recorded judge fixtures, the *entire* per-PR eval is deterministic and quota-free.
3. **Raw ungrounded generation hallucinates the format** — a real data point: `gpt-4.1-mini` got the
   orbit values right (SMA 6871, INC 51.6) but emitted an invented JSON-ish format, not a valid GMAT
   `.script`. That is exactly the failure the RAG grounding (V1) + lint gate (V2) + eval (V3) exist
   to catch; it does not affect V4 (the provider abstraction and determinism hold regardless of
   output quality), but it validates the pipeline's premise.
4. **The abstraction is thin.** One `complete()` method; adapters differ only in endpoint + auth, so
   adding a provider is a small, isolated change — the model-agnostic surface the charter promises.

## Proof

Harness: [`v4_provider_proof.py`](./v4_provider_proof.py) — the `Provider` protocol, the four
adapters, the no-default `select()`, and a record/replay determinism check (stdlib only; GitHub
Models via `gh auth token`). Recorded outputs in `v4_provider_fixtures.json`.

```
python v4_provider_proof.py            # selection demo + live record (gh token) + determinism
python v4_provider_proof.py --replay   # deterministic, no model calls
```

**Caveats.** Only the GitHub Models adapter is live-exercised here (no Anthropic/OpenAI key, no
Ollama); the Anthropic and Ollama adapters are interface-validated. The recorded generations are
real `gpt-4.1-mini` output (ungrounded, so not valid GMAT — see finding 3). CI needs a personal
`MODELS_PAT`; `gh auth token` is local-only.
