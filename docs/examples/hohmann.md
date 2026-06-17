# Draft a Hohmann transfer

A worked end-to-end draft: turn a request for a two-burn Hohmann transfer into a validated GMAT
`.script`. This needs a [model configured](../providers.md) — the example uses Anthropic.

## From the library

```python
from gmat_copilot import draft

result = draft(
    "A Hohmann transfer from a 400 km circular Earth orbit to a 35786 km circular orbit: "
    "raise apogee with an impulsive burn, coast to apogee, then circularise with a second "
    "burn. Report the semi-major axis before and after.",
    model="anthropic:claude-...",
)

print(result.script)        # the generated GMAT .script
print(result.lint.clean)    # did it lint clean?
result.save("hohmann.script")
```

The phrasing carries the parts a correct transfer needs: the two orbits, two impulsive burns, the
coast to apogee between them, and the reported quantity. The retrieval layer grounds the draft in the
relevant GMAT resources (`Spacecraft`, `ImpulsiveBurn`, `Propagator`, `ReportFile`) and command
syntax (`Maneuver`, `Propagate ... {Sat.Apoapsis}`), so the model writes against real syntax.

Inspect what came back through the [result schema](../output-schema.md):

```python
if not result.lint.clean:
    for d in result.lint.diagnostics:
        print(f"{d.line}:{d.column}: {d.severity.value}: {d.rule}: {d.message}")

for chunk in result.retrieval.chunks:
    print(f"{chunk.score:.3f}  {chunk.source}")   # the grounding the draft used
```

By default `draft` runs in **strict** mode: a draft that does not lint clean raises `DraftRejected`,
with the offending result attached so you can inspect it.

```python
from gmat_copilot import DraftRejected

try:
    result = draft("...", model="anthropic:claude-...")
except DraftRejected as exc:
    print(exc)                       # why it was rejected
    print(exc.result.script)         # the best-effort draft
    print(exc.result.lint.warnings)  # and its diagnostics
```

Pass `strict=False` to get the best-effort draft with its diagnostics attached instead of an
exception.

## From the CLI

```bash
gmat-copilot "A Hohmann transfer from a 400 km circular Earth orbit to a 35786 km circular \
orbit: raise apogee, coast to apogee, then circularise; report SMA before and after." \
  --model anthropic:claude-... -o hohmann.script
```

The script is written to `-o` (default `mission.script`; `-o -` for stdout) and a one-line lint
summary is printed to stderr. Strict mode (the default) exits non-zero and writes nothing if the
draft does not lint clean; `--permissive` writes the best-effort draft anyway.

Generation produces the script — **review and run it in GMAT** before trusting the trajectory. The
lint gate catches malformed scripts, not wrong physics.
