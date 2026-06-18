# Provenance

Every draft carries a **provenance** record — a versioned account of how it was produced: the
request, the model, the corpus chunks that grounded it, every attempt the [repair loop](repair.md)
made, and which one won. It makes a generated mission auditable: what was retrieved, what each attempt
produced, and why the loop stopped.

Provenance is **always populated in memory** — it is the trace the [result](output-schema.md) already
holds. The on-disk `.copilot.json` sidecar is written **only on request**, never silently.

## In the result

`result.provenance` is a `Provenance`:

```python
result = draft("a 500 km LEO at 51.6 degrees", model="anthropic:claude-...")

prov = result.provenance
prov.request                 # the natural-language intent
prov.provider, prov.model    # the resolved provider and model (names only — no credentials)
prov.retrieval               # the RetrievalTrace that grounded the draft
prov.repair.stop_reason      # why the loop stopped: clean / budget / no-progress / oscillation
prov.outcome.winner          # index, into prov.repair.attempts, of the draft that won
prov.outcome.passed          # did the winning draft pass under the active mode?

for attempt in prov.repair.attempts:
    print(attempt.passed, attempt.feedback_tier)   # the per-attempt history
```

It carries no credentials — only provider and model *names*.

## The `.copilot.json` sidecar

Saving with `sidecar=True` (or `--provenance` on the CLI) writes the provenance beside the script. For
`mission.script`, the sidecar is `mission.script.copilot.json`:

```python
result.save("mission.script", sidecar=True)
```

The JSON is the same record in a flat, stable shape — sorted keys and an indented body, so a recorded
sidecar diffs cleanly run to run:

```json
{
  "schema_version": 1,
  "request": "a 500 km LEO at 51.6 degrees",
  "provider": "anthropic",
  "model": "claude-...",
  "retrieval": {
    "chunks": [
      { "source": "help/Spacecraft", "score": 0.62, "text": "..." }
    ]
  },
  "drafts": [
    {
      "script": "...",
      "lint": { "diagnostics": [ { "rule": "...", "severity": "ERROR", "message": "...", "line": 12, "column": 3 } ] },
      "dry_run": { "tier": "load", "ok": false, "converged": null, "one_line": "...", "raw_log": "..." },
      "passed": false,
      "feedback": [ "..." ],
      "feedback_tier": "lint",
      "usage": { "input_tokens": 0, "output_tokens": 0 }
    }
  ],
  "outcome": {
    "winner": 0,
    "passed": true,
    "strict": true,
    "stop_reason": "clean",
    "usage": { "input_tokens": 0, "output_tokens": 0 }
  }
}
```

The top-level keys:

| Key | What it holds |
| --- | --- |
| `schema_version` | the writer stamps it and a reader checks it, so later additions stay additive, not breaking |
| `request` | the natural-language intent |
| `provider`, `model` | the resolved provider and model names (never credentials) |
| `retrieval` | the corpus chunks used — each chunk's `source`, `score`, and `text` |
| `drafts` | the per-attempt history: for each attempt, its `script`, `lint` report, `dry_run` result (`null` until the dry-run is reached), whether it `passed`, the `feedback` fed forward, the `feedback_tier`, and token `usage` |
| `outcome` | the `winner` (an index into `drafts`), the final `passed` flag, the active `strict` mode, the `stop_reason`, and aggregate `usage` |

The in-memory and on-disk shapes differ in one place: in memory the draft history and stop reason live
on `provenance.repair` (`.attempts`, `.stop_reason`), while the sidecar flattens the attempts to a
top-level `drafts` list and folds `stop_reason` into `outcome`.

## Reading a sidecar back

`read_sidecar` parses a `.copilot.json` back into a `Provenance`:

```python
from gmat_copilot import read_sidecar

prov = read_sidecar("mission.script.copilot.json")
print(prov.repair.stop_reason, len(prov.repair.attempts))
```

The reader checks `schema_version`: a sidecar written by a newer version than the reader understands
raises `ValueError` rather than mis-parsing. See [Read the provenance](examples/read-the-provenance.md)
for a worked example, and the [API reference](api.md) for the full type signatures.
