# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[0.1.0]: https://github.com/astro-tools/gmat-copilot/releases/tag/v0.1.0
