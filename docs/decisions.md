# Design decisions

A release-frozen summary of the decisions that shape gmat-copilot. The full internal record (with
context and rationale, and the prerequisite-spike measurements behind each) lives in the project's
`docs/design/decisions.md`.

- **Corpus & grounding.** Retrieval is grounded in the GMAT help pages, the stock sample scripts, the
  GmatFunctions, the gmat-script field catalogue, and a curated set of domain notes. The GMAT material
  is Apache-2.0 (redistributable with attribution); the domain notes are MIT. The corpus is extracted
  by maintainers at build time and shipped as text plus a prebuilt index, so **users never need a GMAT
  install** to generate.

- **Model-agnostic, no default.** Generation goes through one `Provider` abstraction with adapters for
  Claude, OpenAI, Ollama, and a recorded provider. **There is no default model** — you choose a
  provider explicitly; with none chosen the tool lists the providers it can reach rather than picking
  one. API keys are read from the environment, never committed.

- **Validation.** Generated scripts are checked against the gmat-script linter. In strict mode a draft
  that does not lint clean (no errors *or* warnings) is rejected; permissive mode returns it with the
  diagnostics attached. A GMAT dry-run that confirms the script actually executes is planned as a
  later capability.

- **Evaluation.** Quality is measured by a two-layer scorer: deterministic structural checks plus an
  LLM-as-judge for whether a script satisfies the request's intent (two valid scripts of the same
  intent differ in text, so the judge scores intent, not text). The judge runs on a free model and is
  validated for accuracy against a gold standard.

- **Reproducible CI.** Every-merge CI is fully deterministic and free: it replays recorded model
  outputs and judge verdicts, with no live inference. Live model runs happen only on demand (to
  refresh fixtures or run the full suite).

- **Licence & footprint.** MIT-licensed; the base install is light and **GMAT-free**. Provider SDKs and
  the GMAT dry-run support are optional extras you add only if you use them.
