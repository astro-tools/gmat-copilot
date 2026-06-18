# Validation

gmat-copilot validates in two tiers: a **static lint gate** that is always on, and an optional
**dynamic GMAT dry-run**. Every generated script is first checked against the
[`gmat-script`](https://github.com/astro-tools/gmat-script) static linter — GMAT-free, instant, and
deterministic. The linter reports diagnostics at three severities:

- **ERROR** — the script does not parse, or contains a defect GMAT rejects outright.
- **WARNING** — an unknown field, a type mismatch, an enum violation, or a reference that does not
  resolve. Each of these is a hard GMAT load error, not a style nit.
- **INFO** — advisory only (for example, an unused resource).

## Strict and permissive

Validation has two modes:

- **Strict** (the default) rejects a draft that reports any **ERROR or WARNING**. Because every
  WARNING-level rule is a hard GMAT load error, strict treats them as fatal; only INFO is tolerated.
- **Permissive** never rejects: it returns the best-effort script with every diagnostic attached, so
  you can inspect and fix it yourself.

## In code

```python
from gmat_copilot.validate import validate

report = validate(script_text)

report.clean                  # True when the linter reported nothing
report.errors                 # ERROR-severity diagnostics
report.warnings               # WARNING-severity diagnostics
report.blocking(strict=True)  # what would reject the draft in strict mode
```

A diagnostic carries its `rule`, `severity`, `message`, and 1-indexed `line` / `column`.

## The dynamic GMAT dry-run

The lint gate is *static* — it reasons about the script's text without GMAT. An optional second tier
runs the script in a real GMAT to catch what a parse cannot. It is enabled with `--dry-run` on the
CLI or `dry_run=True` on [`draft`](api.md), needs the `[gmat]` extra and a discoverable GMAT install,
and runs **only on a script that already lints clean** — the static gate is the cheap inner loop, so
the dry-run never sees a script lint already rejects.

The dry-run is tiered:

- **Config tier** (`load`) drives GMAT's own loader. It catches what a tree-sitter parse cannot: bad
  numerics, malformed epochs, missing data files, and the unresolved references the static linter is
  too conservative to flag.
- **Execution tier** (`run`) runs the mission and checks solver convergence — entered **only when the
  script declares a `Target` or `Optimize`**, because "ran" is not "solved": a script can load and run
  yet leave a solver unconverged.

"Passes the dry-run" therefore means the script **loads, runs, and — if a solver is present —
converged**. Each dry-run executes in its own fresh subprocess (GMAT holds one process-global state
and cannot re-bootstrap in a single interpreter), so a crash or a runaway solver degrades to a failure
verdict rather than taking down the caller; a wall-clock timeout (default 300 s) bounds a real solver.

A dry-run does **not** merge into the lint report: lint diagnostics are precise (rule, severity, line,
column) and dry-run findings are coarser, so a dry-run lands in its own result tier — the `tier` it
reached, whether it was `ok`, the per-solver `converged` map, a single actionable `one_line` of
feedback, and the `raw_log`. The strict/permissive contract above is unchanged: strict still rejects
on lint error *or* warning, and the dry-run is a strictly additive backstop that runs after the lint
gate passes. A failing dry-run is what feeds the [repair loop](repair.md).

## What validation does not cover

Both tiers together catch *malformed* and *unrunnable* scripts, not *wrong* ones: a script can lint
clean, load, and run and still model the wrong orbit. Review and run a generated mission before you
trust its trajectory.
