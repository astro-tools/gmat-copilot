# Evaluation

Two valid scripts for the same request differ greatly in text, so the eval cannot diff a draft
against a golden script. Instead it scores **intent**, in two layers, and aggregates a pass-rate.
The eval is the tool's correctness surface.

## Two-layer scoring

Each prompt pairs a natural-language *request* with an *intent* string and a *structural spec*. A
draft passes a prompt only if **both** layers pass:

- **Structural** — deterministic, GMAT-free, instant. It settles what it can with the
  [`gmat-script`](https://github.com/astro-tools/gmat-script) linter: the
  [lint ceiling](validation.md) (no ERROR or WARNING) plus the resource types, fields, and commands
  the spec requires a satisfying script to contain.
- **Judge** — an LLM decides the semantic residual the structural layer cannot: does the script
  actually model the requested intent? The judge is told to ignore stylistic differences and to fail
  a script that is syntactically valid but models the wrong orbit, inclination, quantity, maneuver
  direction, target value, or output format.

The golden for each prompt is a *checkable spec* (the structural assertions plus the intent string),
not a golden script.

## The judge protocol

- **Model:** `openai/gpt-4.1-mini` on the GitHub Models free tier, temperature 0.
- **Verdict:** a strict, constrained binary — `{"satisfies_intent": true|false}`.
- **Vote:** run N times (default 3) and take the **majority, failing on a tie**. An unreadable
  verdict is dropped, never counted as a vote.

A pass is `structural AND judge`. The report aggregates the pass-rate within each **difficulty tier**
and overall. The shipped prompt set has **51 prompts** — 20 easy, 18 medium, 13 hard.

## Reproducible, quota-free CI

Per-merge CI must be free and deterministic, so it never calls a live model. The eval runs against a
**recorded bundle** — a directory of three files:

- `prompts.json` — the authored prompt set (the source of truth).
- `completions.json` — recorded provider completions, replayed by the recorded provider.
- `judge.json` — recorded judge verdicts, `{model: {prompt_id: [verdict, ...]}}`.

The structural layer always re-runs live (it is free and deterministic); the judge layer replays the
frozen verdicts. Live GitHub Models runs happen only on demand — to refresh a bundle's fixtures or to
run the full suite — never per merge.

## Running it

```bash
# Deterministic replay of a recorded bundle — no model, no quota, no network:
gmat-copilot eval --recorded <bundle-dir>

# Live run against a prompt set (needs a reachable provider and judge):
gmat-copilot eval --live --prompts <prompts.json> --model anthropic:claude-...

# Run live once and freeze the result into a reusable bundle:
gmat-copilot eval --record <bundle-dir> --prompts <prompts.json> --model anthropic:claude-...
```

`--n` sets the judge votes per prompt and `--pace` inserts a delay between calls to respect a
free-tier per-minute budget. See [Reproduce the eval](examples/reproduce-the-eval.md) for a worked
run against the bundle that ships in the repository.
