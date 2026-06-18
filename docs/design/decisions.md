# gmat-copilot — design decisions (v0.1)

The full internal decision record. Each entry is **Context / Decision / Rationale**. The four
prerequisite spikes (**V1–V4**, in [`spikes/`](./spikes/)) produced these with real measurements;
feature work cites the **D-number** it implements. A release-frozen public subset lives in
[`../decisions.md`](../decisions.md).

These records are the source of truth: where earlier charter or issue text conflicts (notably the
provider default — see **D4**), the decision here governs.

---

## D1 — Package layout

**Context.** gmat-copilot is a model-agnostic natural-language → `.script` harness with a library
and a CLI surface; the layers map onto the four spikes.

**Decision.** `src/gmat_copilot/` with:

- `__init__.py` — the public surface: `draft()` and the `CopilotResult` type; `py.typed`.
- `providers/` — the `Provider` protocol and its adapters (D4).
- `rag/` — corpus ingest, the FAISS index, and the retriever (D2/D3).
- `generate.py` — prompt construction and the generation pipeline.
- `validate.py` — the gmat-script lint gate (D5); the gmat-run dry-run + repair loop land here in v0.2.
- `eval/` — the prompt set, golden criteria, the judge, and the scorer (D6/D7).
- `cli.py` — the `gmat-copilot` console command.

**Rationale.** One source of truth for the public surface; each layer is independently testable and
maps to a spike (`rag`→V1, `validate`→V2, `eval`→V3, `providers`→V4).

## D2 — RAG corpus composition + ship-vs-build

**Context.** Ungrounded models hallucinate `.script` syntax (confirmed in V4); RAG grounds them. The
corpus must be redistributable and must keep the base install GMAT-free.

**Decision.** The corpus is the GMAT **help HTML** (reference *and* the tutorial / how-to / chapter
pages) + the stock **sample scripts** + the **`.gmf` GmatFunctions** + the **gmat-script catalogue**
(structured types/fields/enums) + a hand-written **domain-notes** tier (modeling semantics and the
gotchas the linter catches, seeded from the workspace gmat skills). The User's Guide PDF (the same
DocBook source as the help HTML), the internal spec PDFs, and gmat-python notes are **excluded**.
**Maintainers extract the chunked corpus text at build time** (the gmat-script `fields-*.json`
pattern); the package **ships both the text and a prebuilt FAISS index** for the default embedder and
**rebuilds the index on first use only as a fallback** (non-default embedder or corpus change). The
embedder is a BGE-class model (`bge-small-en-v1.5`).

**Rationale.** The corpus is tiny (≈835 chunks → 1.2 MiB index / 2.6 MiB text, ~5 s build). Shipping
the prebuilt index gives deterministic retrieval — which the eval / leaderboard needs — at trivial
cost, and the embedder must download anyway for query-time embedding, so a prebuilt index adds no new
dependency. Build-time extraction keeps users GMAT-free. (V1)

## D3 — Corpus source licences

**Context.** Redistribution is the load-bearing risk for any GMAT-derived corpus.

**Decision.** The GMAT corpus is **Apache-2.0** (the licence explicitly covers documentation source),
so it is **redistributable with attribution**: ship a `THIRD-PARTY-NOTICES` carrying GMAT's Apache-2.0
attribution alongside the project's MIT `LICENSE`. The domain-notes tier is **first-party content
under the project MIT**. The embedding model is MIT.

**Rationale.** Apache-2.0 content is one-way compatible inside an MIT project given attribution; there
is no contractual block (unlike the org's data-thread projects). (V1)

## D4 — Provider abstraction + auth

**Context.** Generation must be model-agnostic, and CI must be testable without paid, flaky inference.

**Decision.** One thin `Provider` protocol —
`complete(prompt, *, model, temperature, max_tokens) -> Completion(text, provider, model, usage)` plus
`reachable()`. Four adapters satisfy it: Anthropic (a Claude model with the user's key), OpenAI,
Ollama (local), and a Recorded provider. **There is no default model:** selection is explicit
(`provider:model`); with none given, the tool **errors and lists the providers it can reach** from
configured credentials — it never auto-picks or recommends one. An adapter with no credential resolves
but reports `reachable() == False`, so a missing key surfaces as a clear error at call time — never a
silent fallback to another provider. Credentials come from the environment, never committed
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `gh auth token` / `MODELS_PAT` for GitHub Models,
`OLLAMA_HOST`).

**Rationale.** Every provider requires its own credential, so configuring one *is* the choice;
recommending a default would bury a vendor preference in a tool whose whole point is to be
model-agnostic. **This supersedes the earlier "default to a current Claude model" wording** in the
charter and the issue text. (V4)

## D5 — Validation contract

**Context.** Two validation tiers exist: the gmat-script linter (static, GMAT-free, instant) and a
gmat-run dry-run (dynamic, needs GMAT).

**Decision.** The **lint gate is the v0.1 validator**. **Strict mode rejects on lint ERROR *and*
WARNING** — every WARNING-level rule (`unknown-field`, `type-mismatch`, `enum-violation`,
`ref-target-mismatch`) is a hard GMAT load error; only `unused-resource` (INFO) is advisory.
Permissive mode returns the best-effort script with all diagnostics attached. **v0.1 = lint-only.**
**v0.2 = + a tiered gmat-run dry-run** (`Mission.load` first — it catches most dynamic defects; a full
`run` only when solver convergence must be checked) **plus the repair loop**. Known gap:
`undeclared-reference` is conservative (filed upstream on gmat-script); the v0.2 dry-run backstops it
at load.

**Rationale.** Lint catches 7 of 8 static defect classes for free (and `duplicate-name`, which GMAT
silently tolerates); the four WARNING rules are real errors, so strict must reject on them; the
dry-run is mostly a cheap load. (V2)

## D6 — Eval protocol + LLM-as-judge

**Context.** Two valid scripts of the same intent differ greatly in text, so the eval cannot diff
against a golden script; the eval is v0.1's correctness surface.

**Decision.** **Two-layer scoring** — a deterministic **structural** layer (gmat-script: lint ≤ INFO
per D5 + required resource types / fields / commands) settles what it can; an **LLM judge** decides
the semantic residual. The golden is a **checkable spec** (structural assertions + an `intent` string)
with an **authored / Opus gold label**, not a golden script. **Judge = `openai/gpt-4.1-mini`** (GitHub
Models free Low-tier), temperature 0, a strict **structured binary verdict**, **N=3 majority-vote,
FAIL-on-tie**. Per-prompt pass = structural ∧ judge; aggregate pass-rate per difficulty tier. The full
~50-prompt set is built in the eval-suite work; the spike froze the protocol on a 6-prompt pilot.

**Rationale.** Measured **100% accuracy and 100% reproducibility** on the pilot — matching High-tier
`gpt-4.1`, beating `gpt-4o-mini` (which was *reproducibly wrong* on one case). Accuracy, not
reproducibility, is the differentiator, and the authored/Opus gold is what makes accuracy measurable.
(V3)

## D7 — CI inference path + budget

**Context.** Inference must be free-tier only, and LLM output is non-deterministic.

**Decision.** **Per-merge CI runs the eval against recorded fixtures** — the Recorded provider for
generation (V4) + recorded judge verdicts (V3) — fully deterministic, **zero model calls, zero
quota**. The structural layer always runs live (free, deterministic). **Live GitHub Models runs only
on `workflow_dispatch` / fixture-refresh / the v0.3 leaderboard**: `openai/gpt-4.1-mini`, free
Low-tier (150/day); CI authenticates with a **personal `MODELS_PAT`** (the workflow `GITHUB_TOKEN` is
unreliable for inference; `gh auth token` works locally). The "per-PR subset vs full suite" split
**collapses** — per-PR is recorded, so there is no per-PR inference budget to subset.

**Rationale.** Recorded fixtures remove per-PR flakiness and quota entirely; the one-time
reproducibility characterization (D6) is what justifies trusting the frozen verdicts. (V4 / V3)

## D8 — Dependencies + licence rule

**Context.** Keep the base install light and GMAT-free.

**Decision.** **MIT** licence (org convention). Base runtime deps: `gmat-script`,
`sentence-transformers`, `faiss-cpu`, `numpy`. Optional extras: `[anthropic]` / `[openai]` /
`[ollama]` (provider SDKs) and `[gmat]` (gmat-run, for the v0.2 dry-run). A bare `pip install
gmat-copilot` pulls **no provider SDK and no GMAT stack**.

**Rationale.** Generation, lint, and the eval's structural layer need neither GMAT nor any specific
provider; users add only what they use. (charter / V1 / V4)

## D9 — GMAT-free generation guarantee

**Decision.** v0.1 generation + lint validation + the eval's structural layer require **no GMAT
install**. The gmat-run dry-run is an **optional, gated, v0.2** capability behind the `[gmat]` extra
(setup-gmat supplies GMAT in CI).

**Rationale.** The inner loop (lint) is free, instant, and GMAT-free (V2); the corpus ships
pre-extracted (V1). (V1 / V2)

## D10 — Result schema

**Decision.** `CopilotResult` carries the generated `.script` text, the **lint report** (gmat-script
diagnostics mapped to severity / rule / location), the **retrieval trace** (which corpus chunks were
used), and **provider / model / usage**. A **provenance** field is reserved — the v0.2 sidecar logs
the prompt, retrieved chunks, draft history, and lint / dry-run results.

**Rationale.** One stable contract for `draft()` and the CLI; reserving the provenance shape now avoids
a v0.2 schema break. (charter)

## D11 — The recorded eval bundle freezes Opus-gold judge verdicts

**Context.** D6 names the cheap `openai/gpt-4.1-mini` judge (N=3 majority) and D7 freezes its verdicts
into the recorded bundle the per-merge CI replays. But a full judged sweep of the ~50-prompt set is
~204 GitHub Models calls (≈51 generations + 51×3 judge), which exceeds the free Low-tier **daily**
per-model cap (measured: the limit reports `x-ratelimit-type: UserByModelByDay`, a multi-hour
`Retry-After`, and binds at ~65 calls — likely a daily *token* budget, given the RAG-grounded prompts
are large). A complete `gpt-4.1-mini`-judged sweep therefore cannot finish in one quota window.

**Decision.** The committed recorded bundle freezes **Opus-authored gold verdicts** for the judge
layer over **`gpt-4.1-mini` generations** for the completions layer. This spends only the ~51
generation calls (one quota window) and yields gold-quality, deterministic verdicts. The verdicts are
authored **in-session**, not wired into the package — Opus is *not* added as a judge provider. They
are stored in `judge.json` in the model-agnostic **un-modeled form** (`{prompt_id: [verdict]}`), which
`run_recorded` already replays via its fallback, so no judge model is hardcoded and no code changes
are needed. The **`gpt-4.1-mini` judge stays the live judge** for novel scripts — the
`workflow_dispatch` gated-eval run and the v0.3 leaderboard — unchanged.

**Rationale.** This is the V3 "judge once with the strongest judge" pattern carried to its conclusion:
D6 already designates Opus as the gold-label authority the cheap judge is *graded against*, so freezing
the gold itself is the highest-fidelity choice for a one-time recorded reference — and it is the only
route that fits the free-tier daily cap in a single window. Honesty is preserved: the completions are
the real free-tier tool output (what a user gets); the frozen verdicts are labeled gold, not the cheap
model. (D6 / D7 / the daily-cap measurement)

## D12 — gmat-run dry-run integration contract

**Context.** D5 fixed the v0.1 validator as the gmat-script lint gate (static, GMAT-free, instant) and
deferred a gmat-run dry-run to v0.2 as the dynamic tier behind the `[gmat]` extra. V5 characterised
that tier on real model output and the V2 defect corpus against a real GMAT install.

**Decision.** The dry-run is a **tiered gmat-run call**, run **only on a lint-clean script** — D5's
gate is the cheap inner loop, so the dry-run never sees a script lint already rejects.

- **Tiers.** `Mission.load` is the **config tier** — it drives GMAT's own loader and catches what a
  tree-sitter parse cannot: bad numerics, malformed epochs, missing data files, and the
  undeclared-reference case D5's linter is too conservative to flag. `mission.run` +
  `Results.converged` is the **execution tier**, entered **only when a solver is present** (a `Target`
  / `Optimize`), because "ran" is not "solved" — a script can load and run yet leave a solver
  `converged == False`. "Passes the dry-run" therefore means **loads, runs, and (if a solver is
  present) converged**.
- **Subprocess isolation.** gmatpy holds one process-global Moderator and cannot re-bootstrap in a
  single interpreter, so **each dry-run runs in its own fresh subprocess**; a crash or timeout degrades
  to a failure verdict rather than taking down the caller. A wall-clock timeout (default 300 s) bounds
  a runaway solver.
- **Error extraction.** GMAT's raw text is distilled to **one actionable, path-free line**, and the
  path differs by tier. The execution tier reads `GmatRunError.log` (and `Results.converged` names the
  solver that failed); the config tier must **redirect the GMAT log with `gmat.UseLogFile()` before
  loading and read it back**, because `GmatLoadError` is thin ("could not parse '<path>'; check the
  GMAT log") and carries no log of its own. A small extractor keeps the `**** ERROR ****` /
  `Interpreter Exception:` message and strips the sequence/path prefixes and the trailing `in line:`
  noise.
- **Reconciliation with lint (extends D5).** Dry-run findings do **not** merge into the `LintReport`
  (D10): lint diagnostics are precise (rule / severity / line / column) and dry-run findings are
  coarser, so they land in a **separate `dry_run` result tier** (`{tier, ok, converged, one_line,
  raw_log}`). The strict/permissive contract is unchanged — strict still rejects on lint ERROR *and*
  WARNING (D5); the dry-run is a strictly additive backstop that runs after the lint gate passes.

**Rationale.** Measured on a real GMAT install: the config tier catches every dry-run-only defect
except non-convergence (which alone needs the execution tier), confirming the tiered policy. Per
dry-run is a ~0.9 s cold subprocess (GMAT bootstrap ~0.17 s + load ~0.16 s + run ~0.04–0.16 s on small
missions) — cheap enough for a repair loop, with the execution tier behind a timeout because a real
solver is unbounded. The load-log redirect is a workaround for a thin load exception; exposing the load
log on the load error is a carry-forward upstream ask, the dynamic-tier analogue of D5's
undeclared-reference filing. (V5 / extends D5 / D10)

## D13 — repair loop

**Context.** With a dynamic validator (D12) behind the lint gate (D5), a failed draft now carries
actionable feedback. V5 measured whether feeding that feedback back converges, and at what budget.

**Decision.** v0.2 wraps generation in a **bounded repair loop**: generate → lint → (if lint-clean)
dry-run; on any failure, **regenerate** with a repair prompt and re-validate.

- **Repair prompt.** The original request + the failing draft + the **failing tier's** diagnostics
  (lint blocking-lines when lint failed, else the dry-run one-line). Feedback is **lint-first**: lint
  is precise and free, so a lint failure is fixed before the costly dry-run is attempted; the dry-run
  one-line is the backstop for the lint-clean-but-unrunnable drafts the loop exists for.
- **Default retry budget N = 2.** One repair does the work; a second covers prompt-distribution
  variance; beyond that, no-progress and persistent failure dominate, so a larger budget only spends
  tokens.
- **Stop conditions.** The loop stops on the **first runnable draft**, on **budget exhaustion**, on
  **no-progress** (a regenerated draft identical to the previous one, by content hash), or on
  **oscillation** (a draft equal to one seen earlier in the loop).
- **Strict/permissive (extends D5).** The loop runs the same in both modes; only the *terminal*
  handling differs — strict raises on a final draft that still has blocking diagnostics, permissive
  returns the best final draft with every diagnostic (lint and dry-run) attached.

**Rationale.** Measured over real model output: a strong grounded model needed no repair (it emitted a
runnable first draft on every prompt of an easy→hard sample), while a weaker model on hard prompts rose
from one-of-six to four-of-six runnable after a **single** repair and then plateaued — every initial
miss being a lint-clean script the dynamic tier (D12) caught, demonstrating the loop's value end to
end. The plateau (zero for the strong model, one for the weak) sets the small default budget; an
observed no-progress re-draft is why an identical regeneration is a stop condition, not a wasted
attempt. (V5 / extends D5)

## D14 — provenance schema

**Context.** D10 reserved a `provenance` field on `CopilotResult` so the v0.2 trace could be added
without a schema break. With retrieval (D2), generation, the lint gate (D5), the dynamic tier (D12),
and the repair loop (D13) all in place, that trace now has a definite shape worth fixing.

**Decision.** `CopilotResult.provenance` carries a **versioned** record of how a draft was produced,
and an optional **`.copilot.json` sidecar** (e.g. `mission.script.copilot.json`) serialises it next to
a saved script. The schema:

- `schema_version` — an integer the writer stamps and a reader checks, so later additions are additive,
  not breaking.
- `request` — the natural-language intent, plus the resolved `provider` / `model`.
- `retrieval` — the corpus chunks used (source + score): the `RetrievalTrace` (D10).
- `drafts` — the **per-attempt history**, one entry per loop iteration (D13): the draft text, its
  `LintReport`, its `dry_run` tier result (D12) when reached, and the feedback fed into the next
  attempt.
- `outcome` — which draft won, the final pass/fail under the active strict/permissive mode, and
  aggregate `usage` (token totals across attempts).

Provenance is **always populated in memory** — it is the trace the result already holds — while the
sidecar is **written only on request** by the saving surface, never silently. It records the real run
only; it is **not** part of the recorded CI path (D7), which replays frozen fixtures rather than live
traces.

**Rationale.** One stable, versioned record makes a generation auditable — what was retrieved, what
each attempt produced, why the loop stopped — which is the v0.2 payoff of closing the loop and the
substrate the eval and leaderboard read. Reserving the shape against D10's placeholder now means the
field can be filled without a contract break, and keeping it out of the recorded fixtures preserves
D7's determinism. (charter / D10 / extends D7)
