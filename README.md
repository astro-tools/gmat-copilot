# gmat-copilot

**Turn a natural-language request into a GMAT mission `.script` — grounded in the GMAT
documentation, validated against a static linter, and produced through a model you choose.**

> **Status:** Retrieval-grounded generation, the static lint gate, the model-agnostic provider
> abstraction, the two-layer evaluation suite, and the CLI are all in place. A GMAT dry-run and a
> repair loop are planned as a later capability.

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

## Validation contract

Drafts are checked by the static lint gate:

- **Strict** (default) rejects a script that reports any **error or warning** — every warning-level
  rule is a hard GMAT load error.
- **Permissive** returns the best-effort script with every diagnostic attached.

Generation and lint validation need no GMAT install. A dynamic GMAT dry-run that confirms a script
actually executes — plus a repair loop — is a later, optional capability behind the `[gmat]` extra.

## What gmat-copilot is **not**

- **Not** a GMAT replacement or a mission optimiser — it writes the script; GMAT runs it.
- **Not** a correctness guarantee — the lint gate catches malformed scripts, not wrong physics.
  Always review and run generated scripts.
- **Not** a model vendor — it ships no model, recommends none, and never silently falls back to one.

## Documentation

Full docs are at **<https://astro-tools.github.io/gmat-copilot/>** — getting started, the
provider/auth model, the validation contract, the result schema, the evaluation protocol, the corpus
and its licences, worked examples (draft a Hohmann transfer, reproduce the eval, add a provider), an
API reference, and the design decisions.

## License

MIT — see [LICENSE](LICENSE).
