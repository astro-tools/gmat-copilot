# Reproduce the eval

The repository ships a recorded eval bundle, so you can reproduce the eval scores **deterministically
— with no model calls, no quota, and no network**. This is the same path CI runs on every merge.

## Replay the recorded bundle

From a clone of the repository, the bundle lives at `tests/data/eval`:

```bash
gmat-copilot eval --recorded tests/data/eval
```

This replays the frozen provider completions and judge verdicts while re-running the structural layer
live (it is free and deterministic), and prints the per-prompt outcomes, the per-tier pass-rates, and
the aggregate:

```text
leo_circular                 [easy  ] structural=PASS judge=True -> PASS
...
  easy  : ...
  medium: ...
  hard  : ...
pass-rate: ...
```

Because every input is frozen, the numbers are identical on every run. The bundle is three files —
`prompts.json`, `completions.json`, and `judge.json` — as described in the
[evaluation protocol](../evaluation.md).

## Run it live

To evaluate fresh drafts and judge them live, point `--live` at a prompt set and choose a model. This
needs a reachable [generation provider](../providers.md) and a reachable judge (the judge defaults to
`openai/gpt-4.1-mini` on the GitHub Models free tier):

```bash
gmat-copilot eval --live --prompts tests/data/eval/prompts.json \
  --model anthropic:claude-... --n 3 --pace 1.0
```

`--n` sets the judge votes per prompt (majority, fail on tie) and `--pace` inserts a delay between
calls to respect a free-tier per-minute budget.

## Freeze your own bundle

Run the live path once and freeze it into a reusable bundle, then replay it deterministically
thereafter:

```bash
gmat-copilot eval --record my-bundle --prompts tests/data/eval/prompts.json \
  --model anthropic:claude-...
gmat-copilot eval --recorded my-bundle    # same scores, no model calls
```

`--record` writes `completions.json` and `judge.json` next to your `prompts.json`; the prompt set
itself is left untouched as the source of truth.
