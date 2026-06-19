# gmat-copilot

[![CI](https://github.com/astro-tools/gmat-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/astro-tools/gmat-copilot/actions/workflows/ci.yml)
[![Docs](https://github.com/astro-tools/gmat-copilot/actions/workflows/docs.yml/badge.svg)](https://astro-tools.github.io/gmat-copilot/)
[![PyPI](https://img.shields.io/pypi/v/gmat-copilot.svg)](https://pypi.org/project/gmat-copilot/)
[![Python versions](https://img.shields.io/pypi/pyversions/gmat-copilot.svg)](https://pypi.org/project/gmat-copilot/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Turn a natural-language request into a GMAT mission `.script` — grounded in the GMAT
documentation, validated against a static linter, and produced through a model you choose.**

> **Status:** Retrieval-grounded generation, the static lint gate, the model-agnostic provider
> abstraction, the two-layer evaluation suite, and the CLI are all in place — and, behind the
> optional `[gmat]` extra, a GMAT dry-run, a bounded repair loop, and a provenance sidecar close the
> loop from an intent to a script validated against a real GMAT.

gmat-copilot is a library and a CLI for [NASA's General Mission Analysis Tool](https://gmat.gsfc.nasa.gov/).
Generation is *retrieval-grounded*: a request is answered against relevant GMAT help pages, sample
scripts, GmatFunctions, and a curated set of domain notes, so the model writes against real syntax
rather than from memory. Every draft is checked by the
[`gmat-script`](https://github.com/astro-tools/gmat-script) linter before it is returned.

## Install

```bash
pip install gmat-copilot
```

The base install is light and **GMAT-free**. Add the provider you use as an extra:

```bash
pip install "gmat-copilot[anthropic]"   # or [openai], or [ollama]
```

GitHub Models (the free-tier path the eval and CI use) needs no extra — it works on the base install.

The dynamic GMAT dry-run is its own optional extra; it needs a discoverable GMAT install (see
[Close the loop](#close-the-loop)):

```bash
pip install "gmat-copilot[gmat]"
```

## Use it

There is **no default model** — you choose one explicitly as `provider:model`. With none chosen, the
tool lists the providers it can reach from your configured credentials rather than picking for you.

```python
from gmat_copilot import draft

result = draft(
    "A 500 km circular Earth orbit at 51.6 degrees inclination; "
    "propagate one day and report altitude and semi-major axis.",
    model="anthropic:claude-...",
)
print(result.script)       # the generated GMAT .script
print(result.lint.clean)   # did it lint clean?
result.save("mission.script")
```

From the command line:

```bash
gmat-copilot "a sun-synchronous orbit at 700 km" --model anthropic:claude-... -o mission.script
gmat-copilot validate mission.script
```

The script is written to `-o` (default `mission.script`; `-o -` for stdout) and a concise lint
summary is printed. Strict mode (the default) exits non-zero if the draft does not lint clean; pass
`--permissive` to write the best-effort draft anyway. `gmat-copilot draft "<intent>"` is an alias of
the bare form. API keys are read from the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …),
never committed.

## Close the loop

With the `[gmat]` extra installed, a lint-clean draft can be loaded — and, with a `Target`/`Optimize`
solver, run — in a real GMAT, and a bounded repair loop can feed any failure back to the model:

```bash
gmat-copilot "a Hohmann transfer to GEO" --model anthropic:claude-... \
    --dry-run --repair 2 --provenance
# lint: clean; dry-run: ok; retries: 1 -> wrote mission.script (+ mission.script.copilot.json)
```

Here the first draft failed the dry-run and one repair pass produced a runnable script (`retries: 1`).

- `--dry-run` loads (and runs, where a solver is present) the draft in GMAT after it lints clean,
  catching the runtime errors a static parse cannot. It needs the `[gmat]` extra and a discoverable
  GMAT install; without them the flag fails with a clear message, and the default path is unaffected.
- `--repair N` regenerates a failing draft up to `N` times, feeding the lint (and, with `--dry-run`,
  runtime) diagnostics back each round. The default `0` is a single pass.
- `--provenance` writes a `.copilot.json` sidecar next to the script — the request, the per-attempt
  draft history, and the outcome — so a generated mission records how it was produced.

## In your editor

The same engine is available in VS Code through the **GMAT Copilot** extension — install it from the
[VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=astro-tools.gmat-copilot)
or [Open VSX](https://open-vsx.org/extension/astro-tools/gmat-copilot):

- **Draft a Mission from a Description…** — type a prompt, then review the generated script as a diff
  against the active file and **apply it only on accept**. Nothing is written silently and nothing is
  auto-applied; in strict mode a draft that does not lint clean is not applied at all.
- Lint (and the optional dry-run) findings land in the **Problems panel** as inline diagnostics.
- The provider/model is explicit — there is no default — via a **Select the Provider and Model…**
  quick-pick over the providers your credentials can reach.

The extension is a thin client over the engine; all `.script` language features (highlighting,
lint-on-type, hover, formatting) come from the
[GMAT Script](https://github.com/astro-tools/gmat-script) extension, which it depends on. See the
[VS Code docs](https://astro-tools.github.io/gmat-copilot/vscode/) for the commands, settings, and
the apply-to-current-file flow.

## Validation contract

Validation runs in two tiers, static then dynamic:

- **Static lint gate** — always on, GMAT-free, instant. **Strict** (the default) rejects a script
  that reports any **error or warning** (every warning-level rule is a hard GMAT load error);
  **permissive** returns the best-effort script with every diagnostic attached.
- **Dynamic GMAT dry-run** — optional, behind the `[gmat]` extra. On a script that lints clean, GMAT
  loads it (and runs it when a solver is present) to catch the runtime errors a static parse cannot.
  It is a strictly additive backstop; the strict/permissive contract is unchanged.

Generation and the lint gate need no GMAT install — only the dry-run tier does.

## What gmat-copilot is **not**

- **Not** a GMAT replacement or a mission optimiser — it writes and validates the script; GMAT runs
  it. The dry-run *checks* that a script loads and runs; it is not a way to execute missions for
  their results.
- **Not** a correctness guarantee — the lint gate catches malformed scripts, not wrong physics.
  Always review and run generated scripts.
- **Not** an auto-applier — in the editor a draft is shown as a reviewable diff and written only when
  you accept it; it never edits your file unattended.
- **Not** a model vendor — it ships no model, recommends none, and never silently falls back to one.
- **Not** a hosted service — the only thing gmat-copilot hosts is the leaderboard, a presentation-only
  board that scores no submissions live. The library and CLI run entirely on your machine.

## Documentation

Full docs are at **<https://astro-tools.github.io/gmat-copilot/>** — getting started, the
provider/auth model, the validation contract, the repair loop, the result schema and the provenance
sidecar, the VS Code extension, the evaluation protocol, the leaderboard, the corpus and its licences,
worked examples (draft a Hohmann transfer, close the loop, read the provenance, reproduce the eval,
add a provider, drive it from VS Code, reproduce a leaderboard entry), an API reference, and the
design decisions.

The per-model **leaderboard** is hosted as a static Hugging Face Space —
**<https://huggingface.co/spaces/astro-tools/gmat-copilot-leaderboard>** — ranking `provider:model`s
on the evaluation suite. It ranks on a never-committed held-out set (the headline) with the committed
public set shown alongside as the reproducibility anchor, so overfitting the public prompts buys no
rank. Any model can be entered by PRing a recorded bundle that reproduces its public score offline;
the [leaderboard docs](https://astro-tools.github.io/gmat-copilot/leaderboard/) cover how to read the
board and submit an entry.

## License

MIT — see [LICENSE](LICENSE).
