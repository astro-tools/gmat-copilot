# Result schema

Every `draft` call returns one stable contract — a `CopilotResult` — that carries everything a
generation request produces. The CLI and the library share it.

```python
from gmat_copilot import draft

result = draft("a 500 km circular orbit at 51.6 degrees", model="anthropic:claude-...")
```

## CopilotResult

| Field | Type | What it holds |
| --- | --- | --- |
| `script` | `str` | the generated GMAT `.script` text |
| `lint` | `LintReport` | the static lint report for `script` |
| `retrieval` | `RetrievalTrace` | the corpus chunks that grounded the generation |
| `provider` | `str` | the provider that produced the draft |
| `model` | `str` | the model name |
| `usage` | `dict[str, int]` | the provider's token counts, when reported |
| `provenance` | `object \| None` | reserved (see below); always `None` for now |

`result.save(path)` writes `script` to *path* (UTF-8) and returns the written `Path`.

## The lint report

`LintReport` is the raw report; the strict/permissive *decision* lives in the
[validator](validation.md). Its diagnostics are in source order, with severity-filtered views:

```python
result.lint.clean                  # True when the linter reported nothing
result.lint.errors                 # ERROR-severity diagnostics
result.lint.warnings               # WARNING-severity diagnostics
result.lint.infos                  # INFO-severity diagnostics
result.lint.blocking(strict=True)  # what would reject the draft in strict mode

for d in result.lint.diagnostics:
    print(f"{d.line}:{d.column}: {d.severity.value}: {d.rule}: {d.message}")
```

Each `LintDiagnostic` carries its `rule`, `severity`, `message`, and 1-indexed `line` / `column`.

## The retrieval trace

`RetrievalTrace.chunks` is the grounding the generation actually used, most-relevant first. Each
`RetrievalChunk` records the `source` label (which [corpus](corpus.md) tier and origin), the
similarity `score`, and the chunk `text`:

```python
for chunk in result.retrieval.chunks:
    print(f"{chunk.score:.3f}  {chunk.source}")
```

## Reserved provenance

`provenance` is reserved for a richer sidecar — the prompt, the retrieved chunks, the draft history,
and lint/dry-run results — that lands with the dry-run and repair loop. It is kept on the contract
now so adding it later is not a schema break; for now it is always `None`.

The full type signatures are in the [API reference](api.md).
