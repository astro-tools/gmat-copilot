# gmat-copilot

**gmat-copilot turns a natural-language request into a GMAT mission `.script` — grounded in the GMAT
documentation, validated against a static linter, and produced through a model you choose.**

It is a library and a CLI. Generation is *retrieval-grounded*: the request is answered against
relevant GMAT help pages, sample scripts, GmatFunctions, and a curated set of domain notes, so the
model writes against real syntax rather than from memory. Every draft is checked by the
[`gmat-script`](https://github.com/astro-tools/gmat-script) linter before it is returned.

## Principles

- **Model-agnostic, no default.** Generation goes through one [provider abstraction](providers.md)
  with adapters for Claude, OpenAI, Ollama, and GitHub Models. There is no default model — you choose
  one explicitly; with none chosen the tool lists the providers it can reach rather than picking for
  you. API keys are read from the environment, never committed.
- **Validated, not just generated.** A draft is checked by the [static lint gate](validation.md). In
  strict mode a script that does not lint clean (no errors *or* warnings) is rejected; permissive
  mode returns the best-effort script with the diagnostics attached.
- **GMAT-free to generate.** Generation and lint validation need no GMAT install. A dynamic GMAT
  dry-run that confirms a script actually executes is a later, optional capability.
- **Light by default.** A bare install pulls no provider SDK and no GMAT stack — you add only the
  extras you use.

## What gmat-copilot is **not**

- It is **not** a GMAT replacement or a mission optimiser — it writes the script; GMAT runs it.
- It does **not** guarantee a *correct mission* — the lint gate catches malformed scripts, not wrong
  physics. Always review and run generated scripts.
- It does **not** ship or recommend a model, and it never silently falls back to one.

See **[Getting started](getting-started.md)** to install and draft your first script, then
**[draft a Hohmann transfer](examples/hohmann.md)**. The [evaluation protocol](evaluation.md) and the
[corpus and its licences](corpus.md) document how quality is measured and what grounds generation;
the **[Design decisions](decisions.md)** record the choices that shape the tool.
