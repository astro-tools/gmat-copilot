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
| `provenance` | `Provenance` | the versioned record of how the draft was produced (see below) |

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

## Provenance

`provenance` is a versioned `Provenance` record of how the draft was produced: the `request`, the
resolved `provider` / `model`, the `retrieval` trace, the per-attempt draft history (each draft with
its lint report and — when the [dry-run](validation.md) ran — its dry-run result), and the `outcome`
(which draft won, the final pass/fail under the active mode, and aggregate token usage). It carries
no credentials — only provider and model *names*.

It is always populated in memory; the sidecar is written only on request:

```python
result = draft("a 500 km LEO at 51.6 degrees", model="anthropic:claude-...")

result.provenance.repair.stop_reason       # why the loop stopped: clean / budget / ...
for attempt in result.provenance.repair.attempts:
    print(attempt.passed, attempt.feedback_tier)

# Write the script and a mission.script.copilot.json sidecar beside it:
result.save("mission.script", sidecar=True)
```

Read a sidecar back into a `Provenance` with `read_sidecar`:

```python
from gmat_copilot import read_sidecar

prov = read_sidecar("mission.script.copilot.json")
```

The JSON is stable (sorted keys, a stamped `schema_version`) so a recorded sidecar diffs cleanly.
The full type signatures are in the [API reference](api.md).
