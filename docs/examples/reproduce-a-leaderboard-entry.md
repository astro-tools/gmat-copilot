# Reproduce a leaderboard entry

The [leaderboard](../leaderboard.md) ranks `provider:model`s on the eval suite, and its public column
is built to be **re-derived by anyone, offline**. This example walks the entry path end to end: score
a model on the committed public set, freeze a recorded bundle, confirm it reproduces the published
number, and open it as a submission. It is the same path a seed row takes.

The headline ranking is the never-committed **held-out** set, scored only by the maintainer in gated
CI; you reproduce the **public** anchor, which is what the submission carries.

## 1. Choose a model

There is no default model — pick one explicitly and make sure its credential is set:

```bash
pip install "gmat-copilot[anthropic]"   # or the extra for your provider
export ANTHROPIC_API_KEY=...            # the credential that model needs
```

## 2. Score it on the public set and freeze a bundle

Run the live eval against the committed public prompt set and record the run into a reusable bundle:

```bash
gmat-copilot eval --record my-entry --prompts tests/data/eval/prompts.json \
  --model anthropic:claude-... --n 3 --pace 1.0
```

`--record` writes `completions.json` and `judge.json` next to a copy of the prompt set, capturing the
model's drafts and the judge verdicts. `--n` is the judge votes per prompt (majority, fail on tie) and
`--pace` respects a free-tier per-minute budget. (The [reproduce the eval](reproduce-the-eval.md) page
covers the recorded-vs-live distinction in full.)

## 3. Confirm it reproduces offline

Replay the frozen bundle — no model calls, no quota, no network — and check the number is stable:

```bash
gmat-copilot eval --recorded my-entry
```

Because every input is frozen, the per-tier pass-rates and the aggregate are identical on every run.
This determinism is exactly what lets CI re-derive your public score from the same bundle.

## 4. Wire it into the board and verify

Add a seed entry for your model to `leaderboard/seeds.json`, pointing `public_bundle` at the bundle
you froze:

```json
{
  "provider": "anthropic",
  "model": "claude-...",
  "kind": "entry",
  "public_bundle": "my-entry",
  "held_out_bundle": "anthropic__claude-..."
}
```

Then build the board locally and verify it reproduces and leaks nothing:

```console
$ gmat-copilot leaderboard build
wrote 2 row(s) to leaderboard/leaderboard.json
$ gmat-copilot leaderboard verify
verified: 2 public row(s) reproduce; board is aggregate-only
```

`build` scores each seed through the recorded path and ranks on the held-out headline (your held-out
cell stays `pending` until the maintainer scores it). `verify` replays each row's recorded bundle,
checks the public pass-rate and the bundle hash match the published row, and asserts the board carries
no held-out gold. Your held-out cell cannot be filled locally — that is the firewall.

## 5. Open the submission

Open a PR that adds your recorded bundle and the seed entry. CI replays the bundle deterministically,
so your public score is one anyone can re-verify offline from the committed files. The maintainer then
scores your `provider:model` against the private held-out in gated CI — the golds fetched from the
private store, never committed — and publishes the ranked row.

A submission carries only a `provider:model` selector and a recorded bundle. It never carries anything
that can request a held-out gold, so the held-out set stays a clean test of generalisation.

## Next

- [Leaderboard](../leaderboard.md) — the two sets, the firewall, and the full schema.
- [Reproduce the eval](reproduce-the-eval.md) — the recorded bundle and the live eval path.
- [Evaluation](../evaluation.md) — the two-layer scorer and the judge protocol behind the numbers.
