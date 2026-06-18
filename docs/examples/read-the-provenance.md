# Read the provenance

A generated mission can carry a record of how it was produced — the request, the model, the corpus
chunks that grounded it, and every attempt the [repair loop](../repair.md) made. This example writes
that record to a sidecar and reads it back.

## Write the sidecar

Pass `sidecar=True` to `save` (or `--provenance` on the CLI). For `mission.script`, the sidecar is
`mission.script.copilot.json`:

```python
from gmat_copilot import draft

result = draft(
    "a sun-synchronous orbit at 700 km; propagate one day and report the altitude",
    model="anthropic:claude-...",
)
result.save("mission.script", sidecar=True)   # writes mission.script + mission.script.copilot.json
```

The provenance is always populated in memory regardless; `sidecar=True` only adds the on-disk file.

## Read it back

`read_sidecar` parses a `.copilot.json` into a `Provenance`:

```python
from gmat_copilot import read_sidecar

prov = read_sidecar("mission.script.copilot.json")

print(prov.request)                  # the original intent
print(prov.provider, prov.model)     # which model produced it
print(prov.repair.stop_reason)       # clean / budget / no-progress / oscillation
print(prov.outcome.winner)           # index, into prov.repair.attempts, of the draft that won
```

Walk the draft history to see what each attempt produced and what was fed forward:

```python
for i, attempt in enumerate(prov.repair.attempts):
    status = "passed" if attempt.passed else f"failed at {attempt.feedback_tier}"
    print(f"attempt {i}: {status}")
    for line in attempt.feedback:
        print(f"  - {line}")
```

And the grounding the draft was written against:

```python
for chunk in prov.retrieval.chunks:
    print(f"{chunk.score:.3f}  {chunk.source}")
```

## Notes

- The sidecar is stable JSON (sorted keys, an indented body), so a recorded one diffs cleanly between
  runs — useful for committing a generated mission alongside how it was produced.
- It carries **no credentials** — only the provider and model *names*.
- The reader checks the `schema_version`: a sidecar written by a newer version than your reader
  understands raises `ValueError` rather than mis-parsing.

The [Provenance](../provenance.md) page documents the full `.copilot.json` schema.
