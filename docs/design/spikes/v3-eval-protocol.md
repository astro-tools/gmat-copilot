# V3 — eval protocol + LLM-as-judge reproducibility

**Spike question.** Design the evaluation protocol (prompt set, golden acceptance-criteria
scheme, judge design) and confirm an LLM-as-judge is reproducible enough to gate CI. Feeds the
design freeze as **D6**.

## Recommendation (TL;DR, → D6)

- **Two-layer scoring.** A deterministic **structural** layer (gmat-script: lint ≤ INFO per D5
  + required resource types / fields / commands) settles what it can for free; an **LLM judge**
  decides the *semantic* residual (right orbit? right quantity? right maneuver direction? right
  target value? right output format?) that the structural layer cannot see.
- **Golden = a checkable spec, not a script** — structural assertions + an `intent` string for the
  judge. The **gold labels are authored once** (each pilot candidate is built as intent-satisfying
  or not) and serve as the frozen, high-quality reference; the cheap CI judge is *graded against
  that gold* (the "judge it once with the strongest judge" pattern).
- **Judge = `openai/gpt-4.1-mini`** via GitHub Models — **free Low-tier (150/day)**, temperature 0,
  a strict structured verdict (`{satisfies_intent: bool, reason}`), **N=3 majority-vote, FAIL-on-tie**.
  On the pilot it scored **100% accuracy and 100% reproducibility**, matching the High-tier
  `gpt-4.1` and beating `gpt-4o-mini`.
- **The numbers are produced once; per-merge CI replays frozen verdicts.** The structural layer
  always runs (free, deterministic); per-merge the judge verdicts are **recorded fixtures**
  (deterministic, zero model calls, zero quota); the live judge runs only to refresh fixtures, on
  `workflow_dispatch`, and to judge novel scripts (the v0.3 leaderboard).

## Protocol design (D6)

- **Prompt set** — a ~50-prompt set stratified by *difficulty* (easy: spacecraft + propagate +
  report · medium: maneuvers, coordinate systems, sun-sync · hard: targeting/optimize, ephemeris
  formats) × *capability*. This spike ships a **6-prompt / 14-candidate pilot**; the full 50 is the
  eval-suite work.
- **Golden spec** per prompt: `structural` (required types / fields / commands; lint ≤ INFO) +
  `intent` (prose for the judge) + (v0.2) `dynamic` (dry-run / converges, from V2). Each candidate
  carries an authored gold label.
- **Judge** — `gpt-4.1-mini`, temp 0, structured binary verdict, **N=3 majority-vote, FAIL-on-tie**
  at the gate. Rubric scored strictly against the prompt's `intent`, not free-form.
- **Scoring** — per-prompt pass = structural ∧ judge-satisfies; aggregate pass-rate per difficulty
  tier.
- **CI inference path** (couples to V4/D7): structural always live/free; **per-merge judge = frozen
  replay** of recorded fixtures (deterministic); live judge only on fixture-refresh / dispatch /
  leaderboard. Locally the judge authenticates with `gh auth token` (implicit `models:read`); CI
  needs a **personal-owned `MODELS_PAT`** (the workflow `GITHUB_TOKEN` is unreliable for inference
  on Free-plan orgs).

## Results (pilot, real GitHub Models runs)

Structural layer (deterministic, gmat-script):

- **2/2 structural-bad caught** for free — `leo_circular` with no ReportFile (missing type +
  command) and `iss_groundtrack` with a hallucinated `Spcecraft` (lint ERROR).
- The **12 semantic cases** (6 intent-satisfying, 6 structurally-complete-but-intent-wrong) all
  pass structurally *by construction* — so the judge's blast radius is exactly those 12, and
  structural-alone would wrongly accept all 6 intent-wrong scripts.

LLM judge (12 candidates; accuracy = majority verdict vs gold; reproducibility = run-to-run
verdict self-agreement):

| model | tier | M | accuracy | reproducibility | neg-control (sem-bad failed) |
|---|---|---|---|---|---|
| `openai/gpt-4.1-mini` | Low (150/day) | 6 | **100%** | **100%** | 6/6 |
| `openai/gpt-4o-mini` | Low (150/day) | 3 | 92% | 100% | 6/6 |
| `openai/gpt-4.1` | High (50/day) | 3 | **100%** | **100%** | 6/6 |

Total ≈ 144 calls, within the free Low (≈108) and High (36) daily caps. Frozen verdicts replay to
identical scores with zero model calls.

## Findings

1. **Reproducibility was not the risk; accuracy is.** All three models gave **100% run-to-run
   verdict agreement** under temp-0 + a constrained binary schema — even though GitHub-Models text
   output is *not* byte-deterministic (an earlier finding). The *verdict* is stable even when the
   prose isn't. So the feared judge flakiness did not appear on clear-cut cases; N=3 majority-vote +
   FAIL-on-tie is kept as a cheap margin for the subtler full-50.
2. **A model can be reproducibly wrong.** `gpt-4o-mini` failed `raise_apogee.good` on all 3 runs —
   it did not recognise that a prograde (+Element1, VNB) burn raises apogee. Perfect self-agreement,
   wrong answer. This is why the judge must be graded for **accuracy against gold**, not just
   self-consistency — and why a frozen, authored/Opus gold is the right reference.
3. **`gpt-4.1-mini` is the judge.** Free Low-tier (more daily headroom than `gpt-4.1`'s 50/day
   High tier), and it matched the stronger model's perfect accuracy + reproducibility while beating
   `gpt-4o-mini`. (No Anthropic models are on the GitHub-Models catalogue, so a Claude judge is not
   a CI-reachable option under the free constraint.)
4. **The structural layer meaningfully shrinks the judge's role.** It settled the lint/presence
   defects for free; the judge is reserved for the genuinely-semantic value/intent residual. A
   forward lever: promoting some value checks (e.g. an SMA range) into structural assertions would
   shrink the judge's blast radius further in the full suite.
5. **The negative control holds.** All 6 structurally-valid-but-intent-wrong scripts were judged
   FAIL — the judge is not rubber-stamping syntactically-valid output.

## Proof

Harness: [`v3_eval_proof.py`](./v3_eval_proof.py) — structural scorer (gmat-script) + the GitHub
Models judge (stdlib `urllib`, `gh auth token`) + a **frozen-replay** mode. Pilot data:
[`v3_prompts/`](./v3_prompts/) (prompts + golden specs + candidate scripts); recorded verdicts in
`v3_judge_fixtures.json`.

```
python v3_eval_proof.py                       # live judge (gh auth token), writes fixtures
python v3_eval_proof.py --replay v3_judge_fixtures.json   # deterministic, no model calls
```

**Caveats.** 100% accuracy + reproducibility is on a **12-case pilot with clear-cut intents**; the
full 50 will include subtler cases where the judge may waver — hence the retained majority-vote +
tie-break and the harness's built-in reproducibility measurement, so the eval-suite work re-checks
on the full set. Gold labels are authored (Opus, once); the cheap judge is validated against them.
CI needs a personal `MODELS_PAT`; `gh auth token` works only locally. Verified with `gmat-run`
0.6.0 / gmat-script 0.3.0 on R2026a.
