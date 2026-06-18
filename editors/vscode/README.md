# GMAT Copilot for VS Code

Draft [GMAT](https://gmat.gsfc.nasa.gov/) mission scripts from a natural-language description, review
the result as a diff, and apply it to the active file — with lint (and the optional gmat-run dry-run)
findings surfaced inline in the Problems panel.

This extension is a thin client over the `gmat-copilot` engine. It contributes generation commands
only; the `.script` language itself — syntax highlighting, lint-on-type, hover, formatting — comes
from the **GMAT Script** extension. Install both for the full experience.

## Requirements

- Python with `gmat-copilot` installed (`pip install gmat-copilot`), plus the provider extra for
  whichever model you use (`gmat-copilot[anthropic]`, `[openai]`, `[ollama]`; GitHub Models needs
  none). Point `gmatCopilot.server.pythonPath` at that environment, or put `gmat-copilot-worker` on
  your `PATH`.
- A provider credential in that environment (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GH_TOKEN`,
  or a running Ollama). Credentials are read by the worker process — never stored in settings.
- The dry-run toggle additionally needs the `[gmat]` extra and a discoverable GMAT install.

## Commands

- **GMAT Copilot: Draft a Mission from a Description…** — type a prompt, review the generated script
  as a diff against the active file, and apply it on accept.
- **GMAT Copilot: Draft a Mission from the Selection** — use the selected text (e.g. a comment
  describing the mission) as the prompt.
- **GMAT Copilot: Re-validate the Active Script** — lint the current buffer on demand.
- **GMAT Copilot: Select the Provider and Model…** — pick from the providers your credentials can
  reach. There is no default model: selection is always explicit.

Generation never overwrites your file silently — a draft is shown as a reviewable diff and applied
only when you accept it. In strict mode a draft that does not lint clean is not applied; its
diagnostics explain why.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `gmatCopilot.model` | `""` | The `provider:model` to generate with. No default — set it explicitly. |
| `gmatCopilot.strict` | `true` | Reject a draft that does not lint clean (off = permissive). |
| `gmatCopilot.repair` | `0` | Feed diagnostics back and regenerate up to N times on a failing draft. |
| `gmatCopilot.dryRun` | `false` | After linting, load/run the draft in GMAT (needs the `[gmat]` extra). |
| `gmatCopilot.server.pythonPath` | `""` | Python interpreter with `gmat-copilot` installed (wins over `server.path`). |
| `gmatCopilot.server.path` | `gmat-copilot-worker` | Command used to launch the engine worker. |
| `gmatCopilot.server.args` | `[]` | Extra arguments passed to the worker. |

## License

MIT — see [LICENSE](./LICENSE).
