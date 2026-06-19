# VS Code extension

**GMAT Copilot** brings the same engine into VS Code: describe a mission in plain English, review the
generated `.script` as a diff against the active file, and apply it on accept — with lint (and the
optional GMAT dry-run) findings surfaced inline. It is a thin client over the `gmat-copilot` engine,
which runs in your own Python environment.

Install it from the
[VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=astro-tools.gmat-copilot)
or [Open VSX](https://open-vsx.org/extension/astro-tools/gmat-copilot).

## Division of labour with gmat-script

The extension contributes **generation commands only**. Everything about the `.script` language
itself — syntax highlighting, lint-on-type, hover, go-to-definition, formatting — comes from the
[GMAT Script](https://github.com/astro-tools/gmat-script) extension, which GMAT Copilot declares as a
dependency and VS Code installs alongside it. GMAT Copilot adds authoring-from-English on top of that
language support rather than reimplementing it, so the two compose instead of competing for ownership
of `.script` files.

In practice that means: GMAT Script gives you a first-class `.script` editor; GMAT Copilot lets you
*write* one from a description and re-validate it on demand.

## Requirements

The extension talks to a small worker process that wraps the Python engine, so the engine must be
installed in a Python environment the extension can launch:

1. **Install the engine.** `pip install gmat-copilot`, plus the provider extra for whichever model you
   use (`gmat-copilot[anthropic]`, `[openai]`, `[ollama]`; GitHub Models needs no extra). The dry-run
   toggle additionally needs the `[gmat]` extra and a discoverable GMAT install.
2. **Point the extension at that environment.** Set `gmatCopilot.server.pythonPath` to the interpreter
   that has `gmat-copilot` installed, or put the `gmat-copilot-worker` console script on your `PATH`.
   When neither resolves, the extension degrades gracefully and shows an install hint rather than
   failing silently.
3. **Provide a credential** in that environment — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, a GitHub
   token (`GH_TOKEN` / a `MODELS_PAT`), or a running Ollama. Credentials are read by the worker
   process and are **never stored in settings**.

## Commands

All commands live under the **GMAT Copilot** category in the Command Palette:

| Command | What it does |
| --- | --- |
| **Draft a Mission from a Description…** | Prompt for a description, generate a script, and show it as a reviewable diff against the active file. |
| **Draft a Mission from the Selection** | Use the selected text (e.g. a comment describing the mission) as the prompt. |
| **Re-validate the Active Script** | Lint the current buffer on demand and refresh its diagnostics. |
| **Select the Provider and Model…** | Pick a `provider:model` from the providers your credentials can reach. There is no default — selection is always explicit. |

## Apply to the current file

Generation is **never** an unattended write. When a draft is ready, the extension opens it as a diff
against the active editor and applies it only when you accept:

1. Run **Draft a Mission from a Description…** (or **…from the Selection**) and type your request.
2. The worker generates the script, lints it, and — if the dry-run toggle is on — loads it in GMAT.
3. The result is shown as a **full-document diff** against the active file. Insert-at-cursor and silent
   overwrite are deliberately not offered; the unit of change is the whole script.
4. **Accept** to replace the file's contents, or dismiss to keep your file untouched.

In strict mode (the default) a draft that does not lint clean is **not** applied — its diagnostics
explain why, and you can relax to permissive mode to apply a best-effort draft with its diagnostics
attached. The repair loop, when enabled, runs before the diff is shown, so what you review is the best
draft the loop produced.

## Diagnostics

Lint findings (and, with the dry-run on, GMAT load/run findings) appear in the **Problems panel** and
as inline squiggles, tagged `gmat-copilot` and carrying the originating rule. They are kept distinct
from GMAT Script's own on-type lint stream, so you can tell a generation-time finding from a
language-server one at a glance. **Re-validate the Active Script** refreshes them for the current
buffer without regenerating.

Long-running steps — the repair loop and the dry-run — report progress and can be cancelled; a
cancelled draft leaves your file exactly as it was.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `gmatCopilot.model` | `""` | The `provider:model` to generate with. No default — set it explicitly, or use **Select the Provider and Model…**. |
| `gmatCopilot.strict` | `true` | Reject a draft that does not lint clean (any error or warning). Off = permissive. |
| `gmatCopilot.repair` | `0` | On a failing draft, feed the diagnostics back and regenerate up to this many times. `0` is a single pass. |
| `gmatCopilot.dryRun` | `false` | After linting, load/run the draft in GMAT to catch runtime errors. Needs the `[gmat]` extra and a discoverable GMAT install. |
| `gmatCopilot.server.pythonPath` | `""` | Python interpreter that has `gmat-copilot` installed. Wins over `server.path`. |
| `gmatCopilot.server.path` | `gmat-copilot-worker` | Command used to launch the engine worker when `pythonPath` is unset. |
| `gmatCopilot.server.args` | `[]` | Extra command-line arguments passed to the worker on launch. |

These mirror the CLI: `strict`, `repair`, and `dryRun` are the editor's form of `--permissive`,
`--repair`, and `--dry-run`, and the same [validation contract](validation.md) and
[repair loop](repair.md) apply.

## Next

- [Drive it from VS Code](examples/in-vscode.md) — an end-to-end editor walkthrough.
- [Providers & auth](providers.md) — the model selectors and their credentials.
- [Validation](validation.md) — the static lint gate and the dynamic GMAT dry-run the editor surfaces.
