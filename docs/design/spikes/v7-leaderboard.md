# V7 — per-model leaderboard: hosting + anti-overfitting

**Spike question.** Settle where the per-model leaderboard is **hosted**, how the eval set resists
**overfitting**, the per-model **results schema** + reproducibility, the **seed baselines + budget**,
and the **refresh / protocol-versioning** policy — before the board is built. Feeds the design freeze
as **D16**. Full prototype: [`v7_leaderboard_proof.py`](v7_leaderboard_proof.py).

## Recommendation (TL;DR)

- **Hosting: a *static* Hugging Face Space.** It renders a published `leaderboard.json`; it runs no
  inference and scores no submission. This is forced, not stylistic — the eval's headline layer is an
  **LLM judge** (D6), which costs GitHub Models quota, is daily-capped (D11), and is non-deterministic,
  so it **cannot run in a free public Space**. Scoring lives in the maintainer's **gated CI** (where
  `MODELS_PAT` and D11's gold discipline already are); the Space is presentation only. Gradio is
  rejected: with nothing to score live, a Gradio runtime is needless compute that sleeps on the free
  tier.
- **Anti-overfitting: a committed public anchor + a never-committed held-out headline.** The board
  **ranks on a private held-out set whose golds are never committed**; the public 51-prompt set
  (committed, byte-reproducible, D7) is shown **alongside** as the reproducibility anchor. A large
  *public ≫ held-out* gap is the overfit tell. Overfitting the public prompts cannot buy rank, because
  the headline rubric is one the entrant never sees.
- **Held-out is the headline *by design*, not a fallback.** The org's reproducibility-board precedent
  ships a public-only board because its answer key was *already published and irretractable* — a
  hidden-label firewall was unbuildable on it, so the true competition was deferred to a
  never-committed set. gmat-copilot inherits the same committed public set (D6/D7/D11) but can
  **author a fresh, never-committed held-out from this release**, so the firewall is built in from
  v0.3 — the public set is the anchor, the held-out is the headline.
- **Scoring lives in gated CI, so there is no public probing surface.** The held-out golds never reach
  the Space; every entry is a reviewed PR + a maintainer-triggered CI run. The rate-limit / public-vs-
  private-*subset* apparatus a live public scoring endpoint needs is therefore **not required** here.
- **Results schema** — one `leaderboard.json` row per `provider:model`: the **held_out** aggregate
  (headline), the **public** aggregate (anchor), the **overfit_gap**, the close-the-loop figures
  (D12/D13), `usage`, and a `run` block pinning tool version, judge model, vote count, and the
  recorded-bundle hash. Stamped with an `eval_protocol_version`; rows compare only within a version.
- **Seeds + budget.** Seed with the free GitHub Models the project already runs (`openai/gpt-4.1-mini`
  — also the judge — and one more Low-tier model); the public row is essentially free from the
  committed recorded bundle, and seeding reuses D11's gold-frozen verdicts to fit the free daily cap.
- **Refresh + versioning.** A change to the prompt set / judge / scorer **bumps the protocol version**;
  on a bump the used held-out batch may **graduate into the public set** and a fresh private held-out
  is authored — bounding leakage over time. Re-running the seeds re-publishes the board.

## Hosting — why a static Space, not Gradio

Three shapes were weighed against how the eval actually scores (a deterministic structural layer **and**
a non-deterministic, quota-metered LLM judge, D6):

| Path | Verdict |
|------|---------|
| **Gradio Space scoring submissions live** | Rejected. The headline layer is the LLM judge — quota-capped (D11), non-deterministic, not free per call — so a public Space cannot score on demand. It would also need the private held-out golds *in the Space*, creating a leak surface the design otherwise avoids entirely. |
| **Static Space rendering a published `leaderboard.json`** | **Chosen.** Zero compute, never sleeps, free-tier-trivial. The board data is produced by gated CI and version-controlled; the Space is a thin front end, refreshed from the published JSON via the HF Hub API (`HF_TOKEN`, the org's HF-distribution precedent). |
| **Docs-site page only (no Space)** | Rejected. The charter names the Space as the project's one hosted artifact; the static board *is* that artifact. (The same JSON can also render in the docs site.) |

The load-bearing simplification mirrors the org precedent's "the scorer needs no GPU, so the board is
cheap": here the scorer needs an LLM judge, so the *scoring moves off the Space entirely* and the board
reduces to "what JSON does CI publish, and what does the Space render". Scoring stays in gated CI; the
Space holds no secret and runs no model.

## Anti-overfitting — public anchor, held-out headline

The committed public set and a never-committed held-out play distinct roles:

- **Public set — the reproducibility anchor.** The shipped 51-prompt set + its recorded bundle
  (`prompts.json` + `completions.json` + `judge.json`) score deterministically offline (D7): anyone
  reproduces the public number with no model, no quota, no network, and the bundle's content hash pins
  it. Because the answer key is committed for exactly this reproducibility, the public set **cannot** be
  a hidden benchmark — and is not asked to be.
- **Held-out set — the headline.** A separate, **authored, never-committed** prompt set; its golds (the
  structural specs, the intent strings, and the Opus-gold verdicts, per D11) live only in a private
  store. The board **ranks on the held-out score**; the public score sits beside it. A model that has
  overfit the public prompts shows a large positive *public − held_out* gap and sinks on the headline.

The proof demonstrates the firewall on the real scorer (synthetic data, since the held-out is private
by construction): an `overfit-public` model **tops the public column (1.000 vs 0.500)** yet places
**last on the held-out headline (0.000 vs 1.000)**, below an `honest` model. Ranking on held-out is
precisely what makes that happen — on the public column alone the overfit model would rank first.

### Why no rate-limit / public-vs-private-subset apparatus

A live public scoring endpoint must defend against *probing* (repeated submissions that overfit the
feedback), which is why the org precedent reaches for hidden labels, a held-back private subset, and a
per-user daily rate limit. gmat-copilot has **no public scoring endpoint**: scoring is gated CI, every
entry is a reviewed PR, and the held-out golds never leave the private store. The probing threat does
not exist, so that apparatus is omitted by design — the firewall is *never-committed golds + maintainer-
gated scoring*, simpler and with a smaller leak surface than a self-serve board.

## Submission / verification flow

v0.3 ships the **path**; the first independent entry and the write-up are the v1.0 gate.

1. **Public score (self-serve, reproducible by anyone).** An entrant runs `gmat-copilot eval --live`
   on the committed public set with their `provider:model`, freezes a recorded bundle, and opens a PR
   adding it under a `leaderboard/entries/` path. CI **replays the recorded bundle deterministically**
   (D7) → the public number, which anyone can re-verify offline.
2. **Held-out score (maintainer-run, the headline).** The maintainer scores the entry's `provider:model`
   against the private held-out in gated CI — the golds fetched from the private store, never committed.
   A free-tier-reachable model runs automatically; a key-gated model supplies a secret or a
   maintainer-supervised recorded held-out bundle (the held-out *requests* may be released for
   generation; the *golds* are never released).
3. **Publish.** The maintainer merges the entry; CI regenerates `leaderboard.json` and pushes the
   refreshed board to the Space.

A submission carries only a `provider:model` selector and (for the public score) a recorded bundle —
never anything that can request a held-out gold.

## Results schema + reproducibility

`leaderboard.json` = a header + a ranked `entries` array. Each row:

- `provider`, `model` — the explicit `provider:model` (no default, D4).
- `held_out` — `{pass_rate, by_tier, n_prompts}` (the headline; D6 aggregates per difficulty tier).
- `public` — `{pass_rate, by_tier, n_prompts}` (the reproducibility anchor).
- `overfit_gap` — `public − held_out` (the tell; `null` until both exist).
- `close_the_loop` — `{repair_lift, base_runnable, repaired_runnable, dry_run_agreement}` (D12/D13).
- `usage` — `{generation_calls, judge_calls, …}` (free-tier transparency).
- `run` — `{tool_version, judge_model, n_votes, recorded_bundle_sha16, verified, submitted_by}`.

The header carries `eval_protocol_version`, `generated_at`, `judge_model`, and the `public_set` /
`held_out_set` descriptors (the public set's `n_prompts` + bundle hash + `committed: true`; the
held-out's `committed: false` + private-store note). The **public** number reproduces byte-for-byte
from the committed bundle via `eval --recorded` (D7) — the row's `recorded_bundle_sha16` pins it. The
**held-out** number reproduces only in gated CI against the private store; that asymmetry *is* the
firewall.

## Seed baselines + budget

The board needs entries, but D4 forbids a default — seeds are explicit `provider:model`s the
maintainer chose to run, not a recommendation. Seed with the free GitHub Models already wired into the
gated eval: **`openai/gpt-4.1-mini`** (also the judge) and one more Low-tier model (e.g.
`openai/gpt-4o-mini`). The `gpt-4.1-mini` **public** row is essentially free — it is the already-
committed recorded bundle (pass-rate 0.804 here). A full judged sweep of 51 prompts is ~51 generations
+ 51×3 judge calls, over the free Low-tier daily cap in one window (D11), so seeding reuses D11's
gold-frozen-verdict pattern for the public bundle and the smaller held-out fits a window; live calls
are paced (`--pace 4.5`, as the gated job already does) and split across the `suite` dispatch windows.

## Refresh + protocol versioning

A change to the prompt set, the judge model, or the scorer **bumps `eval_protocol_version`**; entries
rank only within a version (history is kept, labeled by version). On a bump, the matured held-out batch
may **graduate into the public set** — enlarging the reproducible anchor — and a fresh private held-out
is authored, bounding held-out leakage across releases. This reuses the existing release rhythm: the
board refresh is a step in the release cut, not a standing service.

## Results

`v7_leaderboard_proof.py` drives the **real** recorded eval offline (no model, no GMAT, no network) for
the public anchor, then builds a never-committed synthetic held-out in a temp dir and scores two models
through the same `run_recorded`, ranking the board on the held-out headline. Verbatim output:

```
V7 — per-model leaderboard, held-out as the headline (real scorer)
==================================================================

[1] Public set — the committed, reproducible anchor (the recorded bundle, D7):
    seed model       : github:openai/gpt-4.1-mini
    public pass-rate : {"pass_rate": 0.804, "by_tier": {"easy": 0.85, "hard": 0.846, "medium": 0.722}, "n_prompts": 51}
    close-the-loop   : {"dry_run_agreement": {"easy": 1.0, "hard": 0.0, "medium": 0.0}, "repair_lift": 0.5, "base_runnable": 0.25, "repaired_runnable": 0.75}
    bundle sha-256   : a0cab7b3f7de44b4 (pins the result; reproduced offline, no model/quota)
    byte-identical re-run : True

[2] Held-out — the headline ranking (same scorer, a never-committed private bundle):
    #  entry                  HELD-OUT   public     gap  kind
    ---------------------------------------------------------
    1  demo/honest               1.000    0.500  -0.500  illustrative
    2  demo/overfit-public       0.000    1.000   1.000  illustrative
    3  openai/gpt-4.1-mini         -      0.804     -    seed

[3] Integrity checks (all assert-backed, passed):
    - public score is byte-identical across runs (D7)          : True
    - published board is aggregate-only (no held-out golds leak): True
    - held-out bundle written only outside the repo tree        : True
    - the overfit model tops the PUBLIC column                  : True  (1.0 vs 0.5)
    - the HELD-OUT headline ranks the honest model first        : True  (1.0 vs 0.0)
    - the published board is byte-deterministic                 : True

    => Overfitting the public set tops the public column but loses the held-out headline.
       The held-out golds never reach the board; the public anchor reproduces offline.

RESULT: V7 leaderboard + held-out-headline prototype end-to-end = OK
```

## Findings

1. **The headline firewall is a property of the real scorer, not new machinery.** Ranking on the
   held-out aggregate while scoring with the same shipped `run_recorded` is all it takes for an
   overfit-public model to lose rank — the proof's `overfit-public` entry tops the public column and
   places last on the headline. No rate limiter, no subset split, no Space-side secret.
2. **The public anchor is genuinely reproducible.** The committed bundle scores `gpt-4.1-mini` at
   0.804 byte-identically across runs and processes (D7), pinned by a content hash — so an entrant's
   public number is auditable offline by anyone, exactly as the eval already promises.
3. **The held-out leaks nothing.** With scoring in gated CI, the private golds never reach the Space,
   and the published JSON is aggregate-only — the proof asserts the held-out sentinel appears nowhere
   in it, and that the held-out bundle is written only outside the repo tree.
4. **The LLM judge is the one real divergence from the org precedent**, and it points the whole design:
   because the judge cannot run free in a public Space, scoring moves to gated CI and the Space becomes
   a static renderer — which in turn removes the public probing surface that justified the precedent's
   rate-limit / subset apparatus.
5. **Held-out-as-headline is available by design here.** The precedent fell back to a public-only
   reproducibility board because its key was already committed and a forward holdout did not yet exist;
   gmat-copilot authors a fresh never-committed held-out, so it builds the headline firewall from v0.3.

## Proposed D16 (to record at the design freeze)

> **D16 — the leaderboard + anti-overfitting.** The per-model leaderboard is a **static Hugging Face
> Space** (the project's one hosted artifact) rendering a `leaderboard.json` produced by the
> maintainer's **gated CI**; the Space runs no inference and scores no submission — forced by the eval's
> **LLM judge** (D6/D11), which cannot run free in a public Space. The board **ranks on a never-
> committed private held-out set** (the headline) whose golds — structural specs, intent strings, and
> Opus-gold verdicts (D11) — live only in a private store (a private HF Dataset read by gated CI with
> `HF_TOKEN`); the committed **public 51-prompt set** is shown alongside as the reproducibility anchor
> (its number reproduces byte-for-byte offline via the recorded bundle, D7, pinned by the bundle hash).
> A large *public − held_out* gap is the overfit tell. Because scoring is gated CI and the golds never
> reach the Space, there is **no public probing surface**, so no rate-limit / public-vs-private-subset
> apparatus is needed. **Submission flow:** an entrant PRs a recorded bundle for a self-serve,
> reproducible public score; the maintainer scores the entry's `provider:model` against the private
> held-out in gated CI and publishes the row — v0.3 ships this path; the first independent entry is the
> v1.0 gate. **Schema:** one row per explicit `provider:model` (no default, D4) carrying `held_out` /
> `public` aggregates (per-tier, D6), `overfit_gap`, the close-the-loop figures (D12/D13), `usage`, and
> a `run` block pinning tool version / judge / votes / recorded-bundle hash, stamped with an
> `eval_protocol_version` (rows compare only within a version). **Seeds:** explicit free GitHub Models
> (`openai/gpt-4.1-mini` — also the judge — plus one more Low-tier model), the public row free from the
> committed bundle, seeding within the free daily cap via D11's gold-frozen verdicts. **Refresh:** a
> prompt-set / judge / scorer change bumps the protocol version; the matured held-out batch graduates
> into the public set and a fresh private held-out is authored, at the release cadence. (charter v0.3 /
> extends D4, D6, D7, D10, D11, D12, D13)

## Proof

Harness: [`v7_leaderboard_proof.py`](v7_leaderboard_proof.py) — drives the shipped recorded eval
(`run_recorded` / `run_recorded_lift`) on the committed bundles for the public anchor, builds a
never-committed synthetic held-out in a temp dir, scores an honest and an overfit-public model through
the same scorer, ranks the board on the held-out headline, and asserts the firewall + reproducibility +
no-leak properties. stdlib + `gmat_copilot` only; no model, no GMAT, no network.

```
python docs/design/spikes/v7_leaderboard_proof.py      # (or: uv run python ...)
```

**Caveats.** The proof demonstrates the firewall as a property of the *real* scorer with *synthetic*
data — the held-out is private by construction, so a committed proof cannot use real held-out golds
(the same constraint the org precedent's proof worked under, and the reason the proof's held-out lives
only in a temp dir). The `gpt-4.1-mini` public row is real (the committed recorded bundle); the
`demo/*` rows are illustrative, exercising the schema and the ranking. The private-store mechanism (a
private HF Dataset vs a CI secret for the small payload) is a release-time bootstrap detail, like the
existing `MODELS_PAT` / publisher-secret precedents; the load-bearing rule is that the held-out golds
are **never committed**. The live multi-model seeding run is the gated-CI job's work, not the spike's.
Ratify D16 when the board harness and the Space are built against it.
