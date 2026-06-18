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
| `dry_run` | `DryRunReport \| None` | the winning draft's [dry-run](validation.md) result, or `None` when the dynamic tier did not run |
| `provenance` | `Provenance` | the versioned record of how the draft was produced (see [Provenance](provenance.md)) |

`result.save(path)` writes `script` to *path* (UTF-8) and returns the written `Path`. Pass
`sidecar=True` to also write the [provenance sidecar](#provenance) next to it.

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

## The dry-run report

When the [dynamic dry-run](validation.md) runs, `result.dry_run` is a `DryRunReport`; otherwise it is
`None`. It records the `tier` reached (`load` or `run`), whether it was `ok`, the per-solver
`converged` map (or `None`), a single actionable `one_line` of feedback, and the `raw_log`.

```python
if result.dry_run is not None:
    print(result.dry_run.tier, result.dry_run.ok)
```

## Provenance

`result.provenance` is a versioned `Provenance` record of how the draft was produced — the request,
the model, the retrieval trace, the per-attempt [repair](repair.md) history, and the outcome. It is
always populated in memory; pass `sidecar=True` to also write the `.copilot.json` sidecar beside the
script:

```python
result.save("mission.script", sidecar=True)   # also writes mission.script.copilot.json
```

The [Provenance](provenance.md) page documents the record and the on-disk `.copilot.json` schema in
full; the [API reference](api.md) carries the type signatures.
