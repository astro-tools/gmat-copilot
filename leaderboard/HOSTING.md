# Leaderboard hosting — maintainer runbook

The leaderboard is the project's one hosted artifact: a **static Hugging Face Space** that renders the
`leaderboard.json` produced by the gated CI leaderboard job (decision D16). This file is the
maintainer-only operational runbook — the public-facing board, schema, and submission flow are in
[`docs/leaderboard.md`](../docs/leaderboard.md).

Nothing here is secret, but it is operational and lives outside the published docs site and the
distributed package.

## The pieces

| Piece | What | Where |
|-------|------|-------|
| Static front end | `index.html` + `board.js` + `style.css` + `README.md` | committed at `leaderboard/space/` |
| Published board | `leaderboard.json` (aggregates only) | committed at `leaderboard/leaderboard.json`; copied into the Space at publish |
| The Space | renders the board, runs no model | HF Space, id in the `LEADERBOARD_SPACE_REPO` repo variable |
| Held-out store | the never-committed held-out bundles (the golds) | private HF Dataset, id in the `LEADERBOARD_HELDOUT_DATASET` repo variable |
| Publish + score | the gated CI `leaderboard` job | `.github/workflows/ci.yml` |

## One-time bootstrap

All of these need a Hugging Face account in the `astro-tools` org and repo-admin on the GitHub repo.
Run them once; afterwards refreshing the board is a single workflow dispatch.

1. **Create the static Space.** Either via the HF web UI (SDK = *Static*) or:

   ```bash
   huggingface-cli login                 # paste a write token
   huggingface-cli repo create gmat-copilot-leaderboard \
     --repo-type space --space_sdk static --organization astro-tools
   ```

2. **Create the private held-out Dataset.**

   ```bash
   huggingface-cli repo create gmat-copilot-heldout \
     --repo-type dataset --organization astro-tools --private
   ```

3. **Set the repo secret and variables** (the secret is never committed; the variables are public ids):

   ```bash
   gh secret set HF_TOKEN --repo astro-tools/gmat-copilot                      # an HF write token
   gh variable set LEADERBOARD_SPACE_REPO --repo astro-tools/gmat-copilot \
     --body astro-tools/gmat-copilot-leaderboard
   gh variable set LEADERBOARD_HELDOUT_DATASET --repo astro-tools/gmat-copilot \
     --body astro-tools/gmat-copilot-heldout
   ```

   (`MODELS_PAT` for live GitHub Models scoring is already set from the eval suite.)

## Author + upload the held-out (makes the headline real)

The held-out is the ranking headline; until it is scored, every `held_out` cell is `pending`. A fresh
held-out is authored on every eval-protocol bump (see the refresh policy in `docs/leaderboard.md`).

1. **Scaffold a draft** (writes to the gitignored `leaderboard/.cache/`, never the tracked tree):

   ```bash
   python leaderboard/tools/author_heldout.py --count 12
   ```

2. **Author real prompts.** Edit the draft `prompts.json` into never-before-seen held-out prompts
   (same schema as the public set: `id`, `difficulty`, `request`, `intent`, `structural`).

3. **Record a bundle per seed model** (spends GitHub Models quota; pace for the free daily cap):

   ```bash
   DRAFT=leaderboard/.cache/heldout-draft
   gmat-copilot eval --record "$DRAFT/openai__gpt-4.1-mini" \
     -m github:openai/gpt-4.1-mini --judge-model openai/gpt-4.1-mini \
     --prompts "$DRAFT/prompts.json" --pace 4.5
   ```

   The recorded-bundle directory name must match the seed's `held_out_bundle` in
   `leaderboard/seeds.json` (e.g. `openai__gpt-4.1-mini`). Normalise `judge.json` to the flat
   `{prompt_id: verdicts}` form, exactly as the gated CI `seed` step does for the public bundle.

4. **Upload to the private Dataset** — the golds live only here, never in git:

   ```bash
   huggingface-cli upload astro-tools/gmat-copilot-heldout "$DRAFT" . --repo-type dataset
   ```

> **The firewall.** The held-out golds (requests, intents, verdicts) are never committed and never
> shipped to the Space. The published board carries aggregates only; the `leaderboard verify` step
> fails the publish if it ever does not. The draft and recorded bundles live under
> `leaderboard/.cache/`, which is gitignored.

## Refresh / publish the board

The board is rebuilt and pushed by the gated CI `leaderboard` job — a manual dispatch, at the release
cadence or whenever the eval set, judge, or a seed changes:

```bash
# rebuild from committed + fetched bundles and publish to the Space:
gh workflow run ci.yml --repo astro-tools/gmat-copilot \
  -f leaderboard=build -f publish_space=true

# also live-record the second seed model first (spends MODELS_PAT):
gh workflow run ci.yml --repo astro-tools/gmat-copilot \
  -f leaderboard=seed -f publish_space=true
```

The job fetches the private held-out (if `LEADERBOARD_HELDOUT_DATASET` is set), builds the board,
verifies it reproduces offline and leaks no gold, pushes `leaderboard/space/` (front end + the rebuilt
board) to the Space, and uploads the board as a workflow artifact. Commit the refreshed
`leaderboard/leaderboard.json` from that artifact so the committed board stays in step with the Space.

An eval-protocol change bumps `eval_protocol_version` in `leaderboard/seeds.json`; rows compare only
within a version, so the bump is what keeps historical entries comparable.
