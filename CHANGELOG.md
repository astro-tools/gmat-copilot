# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] — 2026-06-19

Two surfaces for the validated generator: an editor integration and a public, comparable
scoreboard. Both build on the existing engine — generation and the static lint gate are unchanged,
and the base install stays GMAT-free.

### Added

- **VS Code extension** — generation commands inside the editor, driving the engine through a thin
  stdio JSON-RPC worker launched in your own Python environment. A draft is shown as a reviewable
  diff and applied only on accept (never auto-applied); lint and dry-run findings surface as inline
  diagnostics, and the provider/model is chosen explicitly from a reachable-providers quick-pick.
  Every `.script` language feature (highlighting, hover, formatting) stays with the gmat-script
  extension, which it depends on. Published to the VS Code Marketplace and Open VSX in lockstep with
  the package (#72, #73).
- **Per-model leaderboard** — a harness that scores each seeded `provider:model` over the evaluation
  suite and writes a ranked `leaderboard.json`. It ranks on a never-committed held-out set as the
  headline, with the committed public set alongside as the offline-reproducible anchor, so a model
  that overfits the public prompts gains no rank; the board carries aggregates only, and a `verify`
  step is the firewall that keeps held-out golds off it. Hosted as a static Hugging Face Space — the
  project's one hosted artifact — rebuilt by a gated CI job and a refresh workflow (#74, #75).

## [0.2.0] — 2026-06-18

Closes the loop from a natural-language intent to a script validated against a real GMAT.
Generation and the static lint gate stay GMAT-free; the new dynamic validation, the repair
loop, and provenance are additive — the dry-run behind an optional extra.

### Added

- **Dynamic GMAT dry-run tier** — behind the optional `[gmat]` extra, a lint-clean draft is
  loaded in a real GMAT (and run when a `Target`/`Optimize` solver is present) to catch the
  runtime errors a static parse cannot. Strictly additive: the strict/permissive lint contract
  is unchanged and the base install stays GMAT-free (#58).
- **Bounded repair loop** — `draft()` can feed a failing draft's lint (and, with the dry-run,
  runtime) diagnostics back to the model and regenerate, lint-first. Opt-in; it stops at the
  first runnable draft, on budget exhaustion, or when a regenerated draft stops changing (#59).
- **Provenance** — every result carries a versioned record of how it was produced (the request,
  the model, the retrieval trace, the per-attempt draft history, and the outcome), always
  populated in memory and optionally serialised to a credential-free `.copilot.json` sidecar
  next to a saved script (#60).
- **CLI `--dry-run` / `--repair N` / `--provenance`** — drive the dynamic tier, the repair loop,
  and the sidecar from the command line; the summary line reports the lint, dry-run, and retry
  outcome (#61).
- **Eval close-the-loop tier** — the evaluation suite gains a dry-run-agreement tier and measures
  the repair loop's lift, with a `workflow_dispatch` input to select the live suite in CI (#62, #65).

## [0.1.0] — 2026-06-17

Initial public release. gmat-copilot turns a natural-language request into a GMAT mission
`.script`, retrieval-grounded in the GMAT documentation and validated against a static linter,
through a model you choose. Generation and validation need no GMAT install.

### Added

- **`draft()` and `CopilotResult`** — the public entry point. It retrieves grounding context,
  builds the prompt, calls the chosen provider, extracts the fenced `.script` from the response,
  lint-checks it, and returns a `CopilotResult` carrying the script, the lint report, and the
  retrieval trace. `CopilotResult.save()` writes the script to disk; a strict gate (the default)
  raises `DraftRejected` when the draft does not lint clean (#24).
- **Model-agnostic provider abstraction** — adapters for Anthropic (Claude), OpenAI, Ollama, and
  GitHub Models, selected explicitly as `provider:model`. There is no default model and no silent
  fallback: with none chosen, the tool lists the providers reachable from your configured
  credentials rather than picking one. A recorded test provider keeps generation tests offline and
  deterministic (#25).
- **Retrieval-grounded context** — a build tool ingests GMAT help pages, sample scripts,
  GmatFunctions, and a curated set of domain notes into a corpus with a prebuilt FAISS index that
  ships inside the wheel; a query-time retriever assembles a token-budgeted grounding context for
  each request, so the model writes against real syntax rather than from memory (#26, #27).
- **Static lint gate** — every draft is checked by the
  [`gmat-script`](https://github.com/astro-tools/gmat-script) linter before it is returned. Strict
  mode rejects a script that reports any error or warning; permissive mode returns the best-effort
  script with every diagnostic attached (#28, #30).
- **CLI (`gmat-copilot`)** — generate a `.script` straight from an intent, write it to `-o` (or
  stdout) and print a concise lint summary; `gmat-copilot validate <file>` lints an existing
  script. Strict mode exits non-zero on a non-clean draft; `--permissive` writes it anyway. API keys
  are read from the environment, never committed (#32).
- **Two-layer evaluation suite** — a ~50-prompt set with an LLM-as-judge and a scorer, runnable
  reproducibly and wired into CI behind a gated, budget-aware job (#31).
- **Documentation** — an MkDocs-Material site (getting started, the provider and auth model, the
  validation contract, the result schema, the evaluation protocol, the corpus and its licences,
  worked examples, an API reference, and the design decisions), auto-deployed to GitHub Pages on tag
  pushes (#23, #54).
- **Packaging** — a GMAT-free base install with `[anthropic]`, `[openai]`, `[ollama]`, and `[gmat]`
  extras; `CITATION.cff` metadata; and a release workflow that builds, publishes to PyPI via trusted
  publishing, and creates the GitHub release on `v*` tags (#23).

[0.3.0]: https://github.com/astro-tools/gmat-copilot/releases/tag/v0.3.0
[0.2.0]: https://github.com/astro-tools/gmat-copilot/releases/tag/v0.2.0
[0.1.0]: https://github.com/astro-tools/gmat-copilot/releases/tag/v0.1.0
