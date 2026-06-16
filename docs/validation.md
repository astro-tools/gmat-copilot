# Validation

Every generated script is checked against the [`gmat-script`](https://github.com/astro-tools/gmat-script)
static linter — GMAT-free, instant, and deterministic. The linter reports diagnostics at three
severities:

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

## What validation does not cover

The lint gate catches *malformed* scripts, not *wrong* ones: a script can lint clean and still model
the wrong orbit. A dynamic GMAT dry-run that confirms a script actually loads and runs — and a repair
loop that feeds failures back to the model — is a later, optional capability behind the `[gmat]`
extra. Until then, review and run generated scripts before you trust them.
