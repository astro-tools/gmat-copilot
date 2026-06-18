# Close the loop

The static [lint gate](../validation.md) catches malformed scripts; the dynamic GMAT dry-run catches
the ones that lint clean but will not load or run. This example draws on both, and lets the
[repair loop](../repair.md) turn a failing draft into a runnable one.

It needs a [model configured](../providers.md) and the `[gmat]` extra with a discoverable GMAT install:

```bash
pip install "gmat-copilot[gmat]"
```

## From the library

Pass `dry_run=True` to validate each lint-clean draft in GMAT, and `repair=N` to retry on a failure:

```python
from gmat_copilot import draft

result = draft(
    "A Hohmann transfer from a 400 km circular Earth orbit to GEO: raise apogee with an "
    "impulsive burn, coast to apogee, then circularise. Report the semi-major axis before "
    "and after.",
    model="anthropic:claude-...",
    dry_run=True,
    repair=2,
)

print(result.lint.clean)     # the winning draft lints clean
print(result.dry_run.ok)     # ...and loads/runs in GMAT
result.save("hohmann.script")
```

A draft "passes" only when it lints clean **and** loads — and runs, when it declares a
`Target`/`Optimize` solver. The dry-run is the backstop for the drafts the linter cannot fault.

## Inspect what the loop did

Every attempt is recorded in the [provenance](../provenance.md) trace, so you can see each draft, why
it failed, and why the loop stopped:

```python
trace = result.provenance.repair
print(trace.stop_reason)          # clean / budget / no-progress / oscillation

for i, attempt in enumerate(trace.attempts):
    tier = attempt.feedback_tier or "passed"
    print(f"attempt {i}: passed={attempt.passed} tier={tier}")
    for line in attempt.feedback:
        print(f"  - {line}")      # the diagnostics fed into the next attempt
```

A typical run on a hard prompt prints a first attempt that failed at the `load` tier, then a repaired
attempt that passed — the loop's whole purpose.

## Strict and permissive

By default `draft` is **strict**: if the budget is spent and the final draft still has blocking
diagnostics (lint *or* dry-run), it raises `DraftRejected` with the failed result attached.

```python
from gmat_copilot import DraftRejected

try:
    result = draft("...", model="anthropic:claude-...", dry_run=True, repair=2)
except DraftRejected as exc:
    print(exc)                          # why it was rejected, and the retries spent
    print(exc.result.dry_run.one_line)  # the dry-run's one-line feedback
```

Pass `strict=False` to get the best final draft with every diagnostic attached instead of an
exception.

## From the CLI

The same loop from the command line:

```bash
gmat-copilot "A Hohmann transfer from a 400 km circular orbit to GEO; raise apogee, coast, \
then circularise; report SMA before and after." \
  --model anthropic:claude-... --dry-run --repair 2 --provenance -o hohmann.script
# lint: clean; dry-run: ok; retries: 1 -> wrote hohmann.script (+ hohmann.script.copilot.json)
```

The summary names the dry-run outcome and the retries the loop spent; `--provenance` writes the
`.copilot.json` sidecar beside the script. `--dry-run` needs the `[gmat]` extra; asking for it without
the extra fails with a clear message rather than a traceback, and the default no-extra path is
unaffected.

Generation produces the script — **review and run it in GMAT** before trusting the trajectory. A
dry-run confirms a script loads and runs; it does not confirm the physics is what you meant.
