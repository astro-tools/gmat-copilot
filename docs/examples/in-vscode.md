# Drive it from VS Code

A walkthrough of generating a mission in the editor: install the extension, point it at your engine,
draft from a description, review the diff, and apply it. The full reference is the
[VS Code extension](../vscode.md) page; this is the end-to-end path.

## Set up

1. **Install the engine** into a Python environment, with the provider extra you intend to use:

    ```bash
    pip install "gmat-copilot[anthropic]"   # or [openai] / [ollama]; GitHub Models needs no extra
    ```

2. **Install the extension** from the
   [Marketplace](https://marketplace.visualstudio.com/items?itemName=astro-tools.gmat-copilot) or
   [Open VSX](https://open-vsx.org/extension/astro-tools/gmat-copilot). VS Code also installs the
   [GMAT Script](https://github.com/astro-tools/gmat-script) extension it depends on, which provides
   `.script` highlighting and on-type linting.

3. **Point the extension at the engine.** Set `gmatCopilot.server.pythonPath` to the interpreter from
   step 1 (or put `gmat-copilot-worker` on your `PATH`), and make sure that environment has your
   provider credential (e.g. `ANTHROPIC_API_KEY`).

## Pick a model

There is no default model. Run **GMAT Copilot: Select the Provider and Model…** from the Command
Palette; the quick-pick lists only the providers your credentials can reach. Choosing one sets
`gmatCopilot.model` to a `provider:model` selector — for example `anthropic:claude-sonnet-4-6`.

## Draft a mission

Open (or create) a `.script` file so the GMAT Copilot commands are active, then run **GMAT Copilot:
Draft a Mission from a Description…** and type a request:

```text
A 500 km circular Earth orbit at 51.6 degrees inclination; propagate one day
and report altitude and semi-major axis.
```

The extension generates the script in the worker, lints it, and opens the result as a **diff against
the active file**. Review it, then **accept** to replace the file's contents or dismiss to leave the
file untouched. Nothing is written until you accept.

A handy variant: write the description as a comment in the file, select it, and run **Draft a Mission
from the Selection** to use the selection as the prompt.

## Read the diagnostics

Lint findings appear in the **Problems panel** and as inline squiggles, tagged `gmat-copilot`. In
strict mode (the default) a draft that does not lint clean is not applied — the diagnostics tell you
why. Turn off `gmatCopilot.strict` for permissive mode if you want the best-effort draft applied with
its diagnostics attached.

After editing a script by hand, run **GMAT Copilot: Re-validate the Active Script** to refresh the
findings without regenerating.

## Close the loop in the editor

Two optional settings mirror the CLI's dynamic-validation flags:

- `gmatCopilot.repair` — regenerate a failing draft up to N times, feeding the diagnostics back each
  round. The loop runs before the diff is shown, so you review the best draft it produced.
- `gmatCopilot.dryRun` — after linting, load (and run, where a solver is present) the draft in a real
  GMAT to catch runtime errors a static parse cannot. This needs the `[gmat]` extra and a discoverable
  GMAT install in the worker's environment; its findings join the Problems panel.

Both report progress and can be cancelled mid-run; a cancelled draft leaves your file exactly as it
was.

## Next

- [VS Code extension](../vscode.md) — every command and setting in full.
- [Close the loop](close-the-loop.md) — the same dry-run and repair loop from the CLI.
- [Validation](../validation.md) — what the lint gate and the dry-run each catch.
