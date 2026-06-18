# V6 — VS Code / LSP surface + apply-to-current-file UX

**Spike question.** Settle how a VS Code extension drives the gmat-copilot engine and what the
apply-to-current-file UX is, before any extension is built: the engine-integration architecture, the
"does it need its own language server" question and the division of labour with gmat-script's
extension, the apply-to-file UX, inline diagnostics, and the provider/credential UX — and confirm the
org's existing extension packaging precedent transfers. Feeds the design freeze as **D15**.

## Recommendation (TL;DR)

- **A thin stdio JSON-RPC *command worker*, not a language server.** The extension launches
  `python -m gmat_copilot.lsp`-style worker in the user's Python environment (the same
  `pythonPath` / `path` resolution gmat-script's client already uses) and talks JSON-RPC to it over
  stdio. It exposes **generation commands only** (`copilot/draft`, `copilot/validate`); it has zero
  LSP feature handlers.
- **`.script` language features stay with gmat-script.** Syntax highlighting, lint-on-type, hover,
  go-to-definition, and formatting are gmat-script's extension / language server. gmat-copilot
  **depends on** that extension (an `extensionDependencies` entry) and does not reimplement any of
  it. gmat-copilot adds *authoring-from-English* on top of gmat-script's *editing* surface.
- **Shell-out to the CLI is rejected.** The `gmat-copilot` CLI prints human text to stderr
  (`line:col: severity: rule: message`) and has no machine-readable mode; an extension parsing that
  is brittle and gives no place to stream progress or accept cancellation. The worker wraps the
  `draft()` / `validate()` **Python API**, returning structured results.
- **apply-to-current-file is a reviewable diff the user accepts** — a full-document replace surfaced
  through VS Code's native diff/preview, applied only on accept. Never a silent auto-apply (a charter
  non-goal). Lint (and, from v0.2, dry-run) findings map into **VS Code `Diagnostic`s** in the
  Problems panel / inline squiggles, `source = "gmat-copilot"`, `code = <rule>`.
- **Provider/credential UX preserves no-default-model (D4).** `provider:model` is chosen explicitly
  via a `gmatCopilot.model` setting plus a quick-pick listing the *reachable* providers; credentials
  resolve in the worker's environment / VS Code secret storage, never committed, never defaulted.
- **The org's extension packaging precedent transfers wholesale.** esbuild bundle, `@vscode/vsce`
  package, dual publish to the VS Code Marketplace + Open VSX, gated on `VSCE_PAT` / `OVSX_PAT` and
  idempotent on the version tag — gmat-script's `editors/vscode/` is the working template.

## Engine integration — why a worker, not the CLI or an LSP

Three integration shapes were considered against the engine surface as it actually exists
(`draft()` / `validate()` returning a typed `CopilotResult` / `LintReport`; the CLI a thin
text-printing wrapper over them):

| Path | Verdict |
|------|---------|
| **Shell out to `gmat-copilot` CLI** | Rejected. No JSON output (it prints `line:col: severity: rule: message` to stderr and the script to a file / stdout); no progress or cancellation channel; re-parsing human text is fragile across versions. |
| **A full language server (pygls, like gmat-script)** | Rejected as redundant. gmat-copilot has no per-keystroke language intelligence to offer — that is gmat-script's job. A second server competing for `.script` diagnostics would double-publish squiggles and duplicate gmat-script's surface. |
| **A thin stdio JSON-RPC command worker over the Python API** | **Chosen.** Structured results, a natural place for `$/progress` + `$/cancel` on the v0.2 repair loop / dry-run, and it reuses the env/credential-resolution pattern the org's client already ships. |

The worker is launched and located exactly as gmat-script's client launches its server — a
`gmatCopilot.server.pythonPath` (runs `<pythonPath> -m gmat_copilot.lsp`) taking precedence over a
`gmatCopilot.server.path` command, with graceful degradation when neither resolves (the generation
commands simply report the worker is unavailable, with an install hint). This keeps provider
credentials in the Python process's environment, where the existing provider abstraction already
discovers them (D4) — the extension never handles raw keys.

**Long-running steps.** Generation, and especially the v0.2 repair loop and gmat-run dry-run, are
not instant. The worker emits `$/progress` notifications (`generating`, `linting`, and — in v0.2 —
per repair attempt and per dry-run tier) which the client renders in a cancellable VS Code progress
notification; a `$/cancel` request is honoured between repair attempts. The prototype exercises this
channel on the static path (the `generating` / `linting` notifications are real).

## The "LSP" question — division of labour with gmat-script

Fixed so the two extensions compose instead of colliding:

- **gmat-script owns the `.script` language.** The `gmat` language id, the TextMate grammar, and all
  LSP features (diagnostics-on-type, hover, definition, references, document symbols, formatting) are
  gmat-script's. gmat-copilot declares it as an `extensionDependencies` so installing the copilot
  pulls in the language support.
- **gmat-copilot owns generation.** It contributes **commands** — *Draft a mission from a
  description…*, *Apply draft to the active file*, *Re-validate the active script* — and the
  provider/model picker. Its diagnostics are the *post-generation* lint report attached to a specific
  draft (so the user sees why a strict draft was rejected), distinct from gmat-script's
  always-on-type diagnostics. Using a distinct `source = "gmat-copilot"` keeps the two diagnostic
  streams filterable and non-duplicative.
- **`copilot/validate` is a command, not lint-on-type.** It exists for an explicit re-lint of the
  active buffer after an apply; continuous on-type linting remains gmat-script's.

## apply-to-current-file UX

The generated draft is applied as a **full-document replace** presented through VS Code's diff
preview; the edit lands only when the user accepts it. This satisfies the charter's
explicit-and-reviewable requirement and rules out insert-at-cursor (it would interleave a whole
mission into arbitrary text) and silent full-file overwrite (not reviewable). The prototype builds
the edit descriptor (`{"kind": "replaceFullDocument", "newText": ...}`) and the unified diff the
extension shows for review.

Diagnostics surface through the Problems panel and inline squiggles: each `LintDiagnostic`
(1-indexed gmat-script line/column) maps to a 0-indexed VS Code `Diagnostic` range. gmat_copilot's
`LintDiagnostic` keeps only the start position, so the prototype widens the squiggle to end-of-line;
a small enrichment in the extension build can carry gmat-script's full start/end span for a tighter
underline. A strict-rejected draft is **not** applied — the diagnostics explain the rejection and
the user can switch to permissive or refine the prompt.

### Client wiring (the shape the extension build implements)

The TypeScript client is the gmat-script `editors/vscode/` pattern minus the language-server feature
set, plus the generation commands. Sketch:

```ts
// activate(): resolve the worker (pythonPath > path), then register generation commands.
const worker = startWorker(resolveServer(getConfig("gmatCopilot")));   // stdio JSON-RPC child

commands.registerCommand("gmatCopilot.draft", async () => {
  const intent = await window.showInputBox({ prompt: "Describe the mission" });
  const model  = await pickModel(worker);            // quick-pick over reachable providers (D4)
  const res = await window.withProgress(             // $/progress -> cancellable UI
    { location: ProgressLocation.Notification, cancellable: true, title: "gmat-copilot" },
    (_p, token) => worker.request("copilot/draft", { intent, model, strict: true }, token));

  const diags = res.diagnostics.map(toVscodeDiagnostic);              // -> Problems panel
  diagnosticCollection.set(activeUri, diags);
  if (res.rejected) { window.showWarningMessage("Draft rejected; see Problems."); return; }

  await previewAndApply(activeEditor, res.script);   // native diff; WorkspaceEdit only on accept
});
```

## Provider / credential UX in the editor

- **No default model (D4) is preserved in the UI.** A `gmatCopilot.model` setting holds an explicit
  `provider:model`; the *Draft* command opens a quick-pick populated from the worker's reachable
  providers (the worker calls the existing `reachable_providers()`), so the user picks one whose
  credential is configured rather than the extension auto-selecting.
- **Credentials never live in settings.** Keys resolve in the worker environment (the provider
  adapters' existing `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `gh` token / `OLLAMA_HOST` discovery),
  optionally seeded from VS Code secret storage into the child process env. The extension never
  stores a key in `settings.json` and never commits one.

## Packaging baseline

Confirmed against gmat-script's shipped extension — it transfers directly:

- **Bundle:** esbuild (`platform: node`, `target: node18`, `external: ["vscode"]`) → single
  `dist/extension.js`; `vscode-languageclient` is the only runtime dep (the worker reuses its stdio
  transport for Content-Length framing).
- **Activation:** command-triggered (`onCommand:` / `onLanguage:gmat`), so zero cost until used.
- **Tests:** `@vscode/test-electron` activation smoke test under `xvfb-run`, with `pretest`
  building the bundle first.
- **Publish:** a `v*`-tag CI job runs `@vscode/vsce package`, then publishes to the Marketplace
  (`VSCE_PAT`) and Open VSX (`ovsx`, `OVSX_PAT`), each gated on its secret and idempotent
  (skip-if-version-present). The user must bootstrap the `astro-tools` publisher / Open VSX namespace
  and the two secrets before the first tag, or the steps no-op.

## Results

`v6_vscode_surface_proof.py` runs the worker as a subprocess and a simulated VS Code client over the
real stdio boundary, against the recorded provider (no credential, no network, no GMAT):

```
=== copilot/draft: clean draft -> apply-to-current-file ===
  intent: "circular LEO at 500 km, propagate one day, report altitude"
    .. progress: generating
    .. progress: linting
  provider:model = recorded:recorded:fixture   rejected=False
  diagnostics:
    (clean -- no diagnostics)
  apply edit kind: replaceFullDocument (570 chars)
  --- preview diff the user accepts before anything is written ---
    [unified diff: the stub buffer -> the generated mission]

=== copilot/draft: strict rejects a hallucinated field ===
  rejected=True  (strict gate; nothing applied to the editor)
  diagnostics surfaced in the Problems panel:
    [warning] 14:4 unknown-field: unknown field 'DryMas' on Spacecraft 'Sat'  (source=gmat-copilot)

=== copilot/validate: lint the active .script on demand ===
    [warning] 14:4 unknown-field: unknown field 'DryMas' on Spacecraft 'Sat'  (source=gmat-copilot)

=== determinism: identical intent -> identical draft + diagnostics ===
  byte-identical re-draft: True

RESULT: V6 surface prototype end-to-end = OK
```

## Findings

1. **The integration boundary is small and clean.** The worker is ~3 request handlers over the
   existing `draft()` / `validate()` API; the result schema (script + mapped diagnostics + a
   `rejected` flag + a null `dryRun` slot) is everything the editor needs. The risky part of the
   surface was always the *boundary*, and it is thin.
2. **The diagnostic mapping is a one-liner per finding** — 1-indexed → 0-indexed, `source` + `code`
   set — and lands correctly in the Problems panel shape (verified position: the `DryMas` field, VS
   Code range line 14 = source line 15). The only nuance is the squiggle width (start-only today;
   widen with gmat-script's span in the build).
3. **No language server is warranted.** gmat-script already owns every `.script` language feature;
   gmat-copilot adding one would duplicate diagnostics and the grammar. Generation commands +
   `extensionDependencies` is the correct composition, and keeps gmat-copilot's surface to what is
   genuinely new.
4. **The recorded provider makes the surface demoable and testable offline** — byte-identical
   re-drafts, so the extension's activation/round-trip test can run in CI with no inference, exactly
   as the eval already does (D7).
5. **The CLI is the wrong substrate for the editor**, but stays the right one for terminal use; the
   worker and the CLI are siblings over the same API, not a rewrite.

## Proposed D15 (to record at the design freeze)

> **D15 — the VS Code surface.** The extension drives the engine through a thin **stdio JSON-RPC
> command worker** (`python -m gmat_copilot.lsp`-style, launched in the user's Python env with the
> gmat-script `pythonPath` > `path` resolution and graceful degradation) wrapping the `draft()` /
> `validate()` API — **not** a CLI shell-out and **not** a language server. It exposes generation
> commands only (`copilot/draft`, `copilot/validate`); all `.script` language features
> (syntax, lint-on-type, hover, format) remain gmat-script's, declared via `extensionDependencies`.
> **apply-to-current-file** is a full-document replace shown as a reviewable diff and applied only on
> the user's accept (never auto-applied); lint and (v0.2) dry-run findings surface as VS Code
> `Diagnostic`s (`source = "gmat-copilot"`, `code = <rule>`) in the Problems panel / inline
> squiggles. Long-running steps (the repair loop, the dry-run) report via `$/progress` and honour
> `$/cancel`. The **provider/model is explicit** (no default, D4): a `gmatCopilot.model`
> `provider:model` setting plus a quick-pick over reachable providers; credentials resolve in the
> worker environment / secret storage, never committed, never defaulted. Packaging follows the org
> precedent: esbuild bundle, `@vscode/vsce` package, dual Marketplace + Open VSX publish gated on
> `VSCE_PAT` / `OVSX_PAT` and idempotent on the version tag. (charter v0.3 / extends D4, D5, D10,
> D12)

## Proof

Harness: [`v6_vscode_surface_proof.py`](./v6_vscode_surface_proof.py) — the stdio JSON-RPC worker
(generation commands over `draft()` / `validate()`), the simulated VS Code client (subprocess +
JSON-RPC, `$/progress` routing), the diagnostic and apply-to-file mappers, and a determinism check.
Recorded completions in [`v6_vscode_fixtures.json`](./v6_vscode_fixtures.json), keyed by intent to
the `.script` files in [`v6_corpus/`](./v6_corpus). stdlib + gmat_copilot only.

```
python v6_vscode_surface_proof.py            # the client drives the worker (the demo above)
python v6_vscode_surface_proof.py --worker   # internal: the stdio worker, spawned by the client
```

**Caveats.** The prototype proves the *integration boundary* (the novel, risky part) end to end; the
TypeScript client is the well-understood part — its shape is sketched above and the org's
`editors/vscode/` is the living template, so it is not rebuilt here. The recorded provider stands in
for a real `provider:model` (the surface is provider-agnostic by construction, D4). The dry-run tier
needs the `[gmat]` extra and is out of scope for a headless spike: the worker leaves `dryRun` null
and the `$/progress` / `$/cancel` channel it will use is demonstrated on the static path.
