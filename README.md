# gmat-copilot

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
- **Not** a model vendor — it ships no model, recommends none, and never silently falls back to one.

## Documentation

Full docs are at **<https://astro-tools.github.io/gmat-copilot/>** — getting started, the
provider/auth model, the validation contract, the repair loop, the result schema and the provenance
sidecar, the evaluation protocol, the corpus and its licences, worked examples (draft a Hohmann
transfer, close the loop, read the provenance, reproduce the eval, add a provider), an API reference,
and the design decisions.

## License

MIT — see [LICENSE](LICENSE).
