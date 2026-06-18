# Getting started

## Install

```bash
pip install gmat-copilot
```

The base install is light and GMAT-free. Add the provider you intend to use as an extra:

```bash
pip install "gmat-copilot[anthropic]"   # Claude, via your ANTHROPIC_API_KEY
pip install "gmat-copilot[openai]"      # OpenAI, via your OPENAI_API_KEY
pip install "gmat-copilot[ollama]"      # a local Ollama server
```

## Choose a model

There is no default model. Selection is always explicit, as `provider:model`:

| Provider | Example selector | Credential |
| --- | --- | --- |
| Anthropic | `anthropic:claude-...` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai:gpt-...` | `OPENAI_API_KEY` |
| Ollama | `ollama:llama3` | local server (`OLLAMA_HOST`) |
| GitHub Models | `github:openai/gpt-4.1-mini` | `GH_TOKEN` / `MODELS_PAT` |

With no selection the tool errors and lists the providers it can reach from your configured
credentials.

## Draft from the library

```python
from gmat_copilot import draft

result = draft(
    "A 500 km circular Earth orbit at 51.6 degrees inclination; "
    "propagate one day and report altitude and semi-major axis.",
    model="anthropic:claude-...",
)

print(result.script)        # the generated GMAT .script text
print(result.lint.clean)    # did it lint clean?
print(result.provider, result.model, result.usage)

result.save("mission.script")   # write the script to a file
```

The returned [`CopilotResult`](output-schema.md) carries the script, its lint report, the retrieval
trace, and the provider/model/usage.

## Draft from the CLI

```bash
gmat-copilot "a sun-synchronous orbit at 700 km" --model anthropic:claude-... -o mission.script
gmat-copilot validate mission.script        # lint an existing script
gmat-copilot validate mission.script --permissive
```

The script is written to `-o` (default `mission.script`; `-o -` writes to stdout) and a concise lint
summary is printed to stderr. Strict mode (the default) rejects a draft that does not lint clean and
exits non-zero; `--permissive` writes the best-effort draft with its diagnostics attached. With no
`--model` the tool lists the providers it can reach. `gmat-copilot draft "<intent>"` is an alias of
the bare form.

### Close the loop

Three optional flags surface the dynamic-validation capabilities:

```bash
gmat-copilot "a Hohmann transfer to GEO" -m anthropic:claude-... \
    --dry-run --repair 2 --provenance
```

- `--dry-run` loads (and, if the script has a solver, runs) the draft in GMAT after it lints clean,
  catching runtime errors a static parse cannot. It needs the `[gmat]` extra and a discoverable GMAT
  install (`pip install "gmat-copilot[gmat]"`, plus `GMAT_ROOT` or a standard-location install); the
  default no-extra path is unaffected, and asking for `--dry-run` without it fails with a clear
  message rather than a traceback.
- `--repair N` retries a failing draft up to `N` times, feeding the lint (and, with `--dry-run`,
  runtime) diagnostics back to the model each round. The default of `0` is a single pass.
- `--provenance` writes a `.copilot.json` sidecar next to the script — the request, the per-attempt
  draft history, and the outcome — so a generated mission carries a record of how it was produced.

The summary then reports the dry-run outcome and the retries spent. `validate` gains an optional
`--dry-run` too, to dry-run an existing script.

## Next

- [Draft a Hohmann transfer](examples/hohmann.md) — a fuller worked example.
- [Providers & auth](providers.md) — the model selectors and their credentials.
- [Validation](validation.md) — the strict/permissive lint contract.
- [Result schema](output-schema.md) — everything a draft returns.
