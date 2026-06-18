# Repair loop

A first draft is not always a good one. When a draft fails [validation](validation.md), gmat-copilot
can feed the failure back to the model and try again — a **bounded repair loop** that turns a failing
draft into a runnable one without you in the loop.

It is opt-in. The default is a single pass (`--repair 0` / `repair=0`); a positive budget enables the
loop.

## How it runs

Each round is *generate → lint → (if lint-clean) dry-run*:

1. Generate a draft for the request.
2. Lint it. If it does not lint clean, that is the failure.
3. If it lints clean and the [dry-run](validation.md) is enabled, run it in GMAT. If it does not load,
   run, or converge, that is the failure.
4. On a failure, build a repair prompt — the original request, the failing draft, and the failing
   tier's diagnostics — and regenerate.

Feedback is **lint-first**: lint is precise and free, so a lint failure is fixed before the costlier
dry-run is attempted; the dry-run's one-line is the backstop for the lint-clean-but-unrunnable drafts
the loop exists for. The repair budget is the same whether or not the dry-run is enabled — with the
dry-run off, the loop still repairs lint failures, and needs no `[gmat]` extra to do so.

## Stop conditions

The loop stops at the first of:

| Stop reason | Meaning |
| --- | --- |
| `clean` | a draft passed — it lints clean and (if enabled) passes the dry-run |
| `budget` | the retry budget `N` was spent without a passing draft |
| `no-progress` | a regenerated draft was byte-identical to the one before it |
| `oscillation` | a regenerated draft repeated one seen earlier in the loop |

`no-progress` and `oscillation` catch a model that has stopped improving, so the loop spends a retry
only when the draft actually changed.

## Choosing a budget

A small budget does the work. In practice one repair fixes most initial misses, a second covers
prompt-to-prompt variance, and beyond that no-progress and persistent failure dominate — a larger
budget only spends tokens. Start at `1` or `2`.

## In code

```python
from gmat_copilot import draft

result = draft(
    "a Hohmann transfer to GEO; report the semi-major axis before and after",
    model="anthropic:claude-...",
    repair=2,        # up to two repair retries
    dry_run=True,    # validate each clean draft in GMAT (needs the [gmat] extra)
)

print(result.lint.clean)        # the winning draft's lint state
print(result.dry_run)           # its dry-run report, or None if the dry-run was off
```

Every attempt is recorded in the [provenance](provenance.md) trace, so you can see what the loop did
and why it stopped:

```python
trace = result.provenance.repair
print(trace.stop_reason)                 # clean / budget / no-progress / oscillation
for attempt in trace.attempts:
    print(attempt.passed, attempt.feedback_tier)   # e.g. False "lint", then True None
```

## Strict and permissive

The loop runs the same in both [modes](validation.md); only the *terminal* handling differs. After
the budget is spent, **strict** raises `DraftRejected` when the final draft still has blocking
diagnostics (the rejected result is attached for inspection); **permissive** returns the best final
draft with every diagnostic — lint and dry-run — attached.

## From the CLI

```bash
gmat-copilot "a Hohmann transfer to GEO" --model anthropic:claude-... \
    --dry-run --repair 2 --provenance
# lint: clean; dry-run: ok; retries: 1 -> wrote mission.script (+ mission.script.copilot.json)
```

The summary reports the retries the loop spent (`retries: 1` here means the first draft failed and one
repair produced a runnable script). `--repair` works without `--dry-run` too, repairing lint failures
alone. See [Close the loop](examples/close-the-loop.md) for a fuller worked run.
