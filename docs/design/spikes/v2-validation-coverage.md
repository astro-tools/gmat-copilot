# V2 — validation coverage: gmat-script lint vs gmat-run dry-run

**Spike question.** Quantify which `.script` defect classes gmat-script's linter catches
**statically** (no GMAT) versus which surface only at a **gmat-run dry-run**, and fix the
strict/permissive validation contract and the v0.1 (lint-only) / v0.2 (lint + dry-run) split.
Outcome feeds the design freeze as **D5**.

## Recommendation (TL;DR, → D5)

- **Strict mode rejects on lint ERROR *and* WARNING.** Every WARNING-level rule in the sample
  (`unknown-field`, `type-mismatch`, `enum-violation`, `ref-target-mismatch`) is a **hard GMAT
  load error** — a script that "only" warns is not runnable. Only `unused-resource` (INFO) is a
  genuinely non-blocking diagnostic. So the gate is "no ERROR and no WARNING"; INFO is advisory.
- **Permissive mode** returns the best-effort script with all diagnostics attached.
- **v0.1 = the lint gate alone** — it catches 7 of 8 static defect classes for free (no GMAT,
  in-process, instant), and one class (`duplicate-name`) that GMAT itself silently tolerates.
- **v0.2 = lint + a tiered gmat-run dry-run.** The dry-run adds what lint cannot: the
  `undeclared-reference` gap, and numeric/semantic/data defects. It is **tiered** — `Mission.load`
  (cheap) catches 4 of the 5 dry-run-only defects; only **non-convergence** needs a full
  `mission.run`. The v0.2 validator should therefore try load first and only run when a solver is
  present or a deeper check is wanted.
- **File upstream:** `undeclared-reference` is too conservative (below).

## Coverage table

Hand-crafted defect-taxonomy corpus (`v2_corpus/`), measured with real gmat-script lint and a
real gmat-run dry-run on R2026a. "first caught" assumes the *error-only* strict reading, so the
WARNING rows show as load-caught; under the recommended contract (reject on warnings) those move
to lint-caught — that is the point of the recommendation.

| script | defect class | lint | load | run | uniquely / first caught |
|---|---|---|---|---|---|
| unknown_resource_type | unknown-resource-type | **ERROR** | FAIL | FAIL | lint (also load) |
| undeclared_reference | undeclared-reference | clean | FAIL | FAIL | **dry-run only (lint gap)** |
| duplicate_name | duplicate-name | **ERROR** | ok | ok | **lint only (GMAT tolerates)** |
| unknown_field | unknown-field | WARNING | FAIL | FAIL | both — warning is a hard error |
| type_mismatch | type-mismatch | WARNING | FAIL | FAIL | both — warning is a hard error |
| enum_violation | enum-violation | WARNING | FAIL | FAIL | both — warning is a hard error |
| ref_target_mismatch | ref-target-mismatch | WARNING | FAIL | FAIL | both — warning is a hard error |
| syntax_error | syntax-error | **ERROR** | FAIL | FAIL | lint (also load) |
| bad_eccentricity | malformed-numeric (ECC>1, SMA>0) | clean | FAIL | FAIL | dry-run, load tier |
| bad_epoch | malformed-epoch | clean | FAIL | FAIL | dry-run, load tier |
| missing_potential_file | missing-data-file | clean | FAIL | FAIL | dry-run, load tier |
| infeasible_target | infeasible-targeter | clean | ok | no-converge | **dry-run, run tier (convergence)** |
| valid_propagate | — (valid) | clean | ok | ok | — clean through both |
| valid_target_converges | — (valid) | clean | ok | ok (converged) | — clean through both |

Summary: static classes flagged by lint **7/8** (3 ERROR, 4 WARNING); lint-clean-but-dry-run-fail
**5** (4 at load, 1 at run); valid controls clean **2/2**.

## Findings

1. **WARNING ≠ optional.** All four WARNING-level rules are hard GMAT load errors. The validation
   gate must treat ERROR and WARNING as blocking; only INFO (`unused-resource`) is advisory. This
   is the central D5 decision and it resolves the spike's open question (whether strict rejects on
   warnings — yes).
2. **The two tiers are complementary, not redundant — each uniquely catches a class:**
   - *lint-only:* `duplicate-name` — GMAT silently accepts a redefined resource (last wins), so
     only the linter flags the ambiguity. The free static gate has standalone value.
   - *dry-run-only:* `undeclared-reference` — see the gap below; plus all the numeric/semantic/data
     defects that are lint-clean by nature.
3. **The dry-run is mostly a cheap *load*.** 4 of 5 dry-run-only defects (bad elements, bad epoch,
   missing data file, the undeclared ref) fail at `Mission.load`, before any propagation. Only
   **non-convergence** of a solver requires a full `mission.run` plus a `result.converged` check.
   v0.2 should load-first and run only when needed.
4. **GMAT leniency exists in both directions.** Beyond `duplicate-name`, a `Propagator` with no
   `ForceModel` was observed to load and run (GMAT supplies a default) — i.e. not every
   "incomplete" script is a defect. Validation targets *runnability + stated intent*, not stylistic
   completeness.
5. **Linter API fit is good.** `gmat_script.lint(text)` returns `Diagnostic(rule, severity,
   start/end Position, message)` — it maps directly onto the result's diagnostics with no
   massaging. The gap is *coverage*, not API shape.

## Linter gap to file upstream

`undeclared-reference` is conservative to the point of missing common cases. It did **not** fire
for an undeclared reference in a resource-field value (`Prop.FM = <undeclared>`) **or** for an
undeclared target in the mission sequence (`Maneuver <undeclared>(Sat)`) — both came back clean,
while a clearly-undeclared reference is exactly what an LLM produces when it hallucinates a
resource name. (`ref-target-mismatch` works — `Sat.Tanks = {Prop}` is flagged — so the catalogue
plumbing is fine; the scoping rule is just too cautious.) This is the main reason v0.2's dry-run
is load-bearing for the hallucinated-reference failure mode, and a candidate fix to propose
upstream (widen high-confidence ref scoping to resource-field object values and command targets).

## Proof

Harness: [`v2_validation_proof.py`](./v2_validation_proof.py) — lints each corpus script
in-process and dry-runs it in an isolated subprocess (avoids the in-process gmatpy re-init limit
and contains crashes), then prints the coverage table. Portable (`--gmat-root` / `GMAT_ROOT`).

```
python v2_validation_proof.py --gmat-root <gmat-install>
```

Corpus: [`v2_corpus/`](./v2_corpus/) — 14 scripts, each isolating one defect class via a
`% DEFECT:` / `% EXPECT:` header (8 static-class, 5 dry-run-only, 2 valid controls). Minimal and
plugin-free on purpose (a stock sample like the Hohmann tutorial fails to load headlessly because
it pulls in the OpenFrames viewer — irrelevant to validation).

**Caveat (instrument).** An LLM was not reachable in this environment, so the corpus is a curated
taxonomy rather than real model output. This fixes the *capability mapping* (which classes are
static-catchable vs dry-run-only) precisely and deterministically — what D5 needs. The real-model
error *frequency* (how often each class actually occurs) is deferred to the eval suite, where real
providers run; that is where the strict-rejects-on-warnings policy should be re-checked against
real output volume.

Deps: `gmat-script`, `gmat-run` + a GMAT install (the dry-run half). Not base deps — install in a
throwaway env. Verified on R2026a with `gmat-run` 0.6.0 (Python 3.12).
