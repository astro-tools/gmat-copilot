# Leaderboard

The leaderboard ranks `provider:model`s on the [evaluation suite](evaluation.md). It is the
project's one hosted artifact: a `leaderboard.json` produced by gated CI and rendered by a static
front end. Nothing about it scores submissions live — the [judge](evaluation.md#the-judge-protocol)
is quota-metered and non-deterministic, so scoring stays in CI and the board is presentation only.

## Where it lives

The board is hosted as a static **Hugging Face Space**:

**<https://huggingface.co/spaces/astro-tools/gmat-copilot-leaderboard>**

The Space renders the published `leaderboard.json` and runs no model. It is rebuilt from the board by
a refresh workflow whenever the eval set, the judge, or a seed changes; the `eval_protocol_version`
stamped on the board is what keeps historical entries comparable across refreshes.

## Two sets, two roles

Every model is scored on two prompt sets that play opposite roles:

- **Public** — the committed 51-prompt set and its recorded bundle. Its number reproduces
  byte-for-byte offline, with no model and no quota, pinned by the bundle's content hash. Because the
  answer key is committed for exactly this reproducibility, the public set is the **anchor**, not a
  hidden benchmark.
- **Held-out** — a separate, **never-committed** prompt set whose golds live only in a private store.
  The board **ranks on the held-out score**; the public score sits beside it.

A model that has overfit the public prompts shows a large positive **`overfit_gap`** (`public −
held_out`) and sinks on the headline. Ranking on a set the entrant never sees is what makes
overfitting the public prompts buy no rank — no rate limiter or hidden-label apparatus is needed,
because there is no public scoring endpoint to probe.

## The firewall

The board carries **aggregates only** — per-tier pass-rates, the close-the-loop figures, usage, and
a run block. No prompt text, intent, or judge verdict ever reaches it, so a held-out gold cannot leak
through the published JSON. `gmat-copilot leaderboard verify` asserts this on any board, and the
held-out bundles are fetched into a gitignored cache that is never committed.

## Schema

`leaderboard.json` is a header plus a ranked `entries` array. Each entry:

```json
{
  "rank": 1,
  "provider": "github",
  "model": "openai/gpt-4.1-mini",
  "kind": "seed",
  "public":   {"pass_rate": 0.804, "by_tier": {"easy": 0.85, "hard": 0.846, "medium": 0.722}, "n_prompts": 51},
  "held_out": {"pass_rate": null, "status": "pending: scored in gated CI ..."},
  "overfit_gap": null,
  "close_the_loop": {"repair_lift": 0.5, "base_runnable": 0.25, "repaired_runnable": 0.75, "dry_run_agreement": {"easy": 1.0, "hard": 0.0, "medium": 0.0}},
  "usage": {"generation_calls": 51, "judge_calls": 153, "total_tokens": 142775},
  "run": {"tool_version": "...", "judge_model": "openai/gpt-4.1-mini", "n_votes": 3, "recorded_bundle_sha16": "a0cab7b3f7de44b4", "verified": true, "submitted_by": "seed"}
}
```

The `public` and `held_out` cells are the per-difficulty-tier aggregates; `held_out` is `pending`
until it has been scored in gated CI. `overfit_gap` is `null` until both exist. The `run` block pins
the result — `recorded_bundle_sha16` is the content hash that reproduces the public number offline.
The header stamps an `eval_protocol_version`; rows compare only within a version.

## Build it

The board is assembled from a seed config (`leaderboard/seeds.json`) that names each explicit
`provider:model` and its recorded bundle. There is no default model — a seed is a model the
maintainer chose to run.

```console
$ gmat-copilot leaderboard build
wrote 1 row(s) to leaderboard/leaderboard.json
```

`build` scores each seed through the recorded path, ranks on the held-out headline, and writes the
board. A seed with no recorded public bundle available is skipped with a note. Pass `--held-out
<dir>` to score against held-out bundles fetched from the private store; without it, every held-out
cell stays pending.

## Reproduce a public score

Anyone can re-derive the public numbers offline — the audit the board promises:

```console
$ gmat-copilot leaderboard verify
verified: 1 public row(s) reproduce; board is aggregate-only
```

`verify` replays each seeded row's recorded bundle, checks the public pass-rate and bundle hash match
the published row, and asserts the board carries no held-out gold. The held-out cells are not
re-derived — they reproduce only in gated CI against the private store, which is the firewall.

## Submit an entry

The path is the same for an independent entry as for a seed:

1. Run `gmat-copilot eval --live` on the committed public set with your `provider:model`, freeze a
   recorded bundle, and open a PR adding it. CI replays the bundle deterministically for a public
   score anyone can re-verify offline.
2. The maintainer scores your `provider:model` against the private held-out in gated CI — the golds
   fetched from the private store, never committed — and publishes the row.

A submission carries only a `provider:model` selector and a recorded bundle; it never carries
anything that can request a held-out gold.
