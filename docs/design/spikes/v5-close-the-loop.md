# V5 — close the loop: gmat-run dry-run signal + repair-loop convergence

**Spike question.** Settle the two open questions behind v0.2's "close the loop" before any feature
work: (a) how usable the **gmat-run dry-run** error signal is as model feedback and how to extract /
tier it at the package boundary, and (b) whether feeding lint **and** dry-run errors back to a real
model actually **converges**, and at what **retry budget N**. Gates the dry-run tier, the repair
loop, and the provenance sidecar. Outcome feeds the design freeze.

> **Decision numbering.** The internal record already uses **D11** (the recorded eval bundle, v0.1).
> The earlier issue text assumed v0.2 would record D11/D12/D13; since D11 is taken and the decision
> record governs, this spike feeds **D12** (dry-run integration contract) and **D13** (repair loop),
> leaving **D14** for the provenance sidecar. The freeze should adopt that numbering.

## Recommendation (TL;DR → D12 + D13)

- **Dry-run is a tiered gmat-run call behind the `[gmat]` extra (→ D12).** `Mission.load` is the
  cheap config tier; `mission.run` + `Results.converged` is the execution tier. The load tier alone
  catches every dry-run-only defect except solver non-convergence; only a solver needs the run tier.
  Measured cost: a full **cold dry-run subprocess is ~0.8–1.0 s** (Python + `gmat_run` import + GMAT
  bootstrap ~0.17 s + load ~0.16 s + run ~0.04–0.16 s for small missions). The run tier is cheap
  here but unbounded in general (a real solver can spin), so it stays behind a timeout and runs only
  when a solver is present.
- **Error extraction is asymmetric and needs a log redirect (→ D12).** Run-tier failures carry the
  full GMAT log on `GmatRunError.log` — distil it directly. Load-tier failures **do not**: gmat-run's
  `GmatLoadError` is thin ("could not parse '<path>'; check the GMAT log file") and carries no log.
  To recover an actionable load-tier line, **redirect the GMAT log with `gmat.UseLogFile()` before
  loading** and read it back. With that, a ~6-line regex distils every defect class to **one clean,
  actionable, path-free feedback line**.
- **Each dry-run runs in a fresh subprocess (→ D12).** gmatpy holds one process-global Moderator and
  cannot re-initialise in a single interpreter, so a repair loop that dry-runs several drafts must
  isolate each in its own process (the gmat-sweep / astrodynamics-mcp pattern). The cost is the
  ~0.9 s cold start above; a 300 s timeout bounds a runaway solver.
- **Dry-run findings land in a separate tier, not mixed into the lint report (→ D12).** Lint runs
  first (free, precise rule/severity/line, in-process); the dry-run runs **only on lint-clean
  scripts** (the tiered D5 contract) and backstops lint's gaps — the `undeclared-reference` hole plus
  every numeric / semantic / data / convergence defect lint cannot see. The result gains a `dry_run`
  field `{tier, ok, converged, one_line, raw_log}`; it does not pollute the `LintReport`.
- **Repair loop: bounded, lint-then-dry-run feedback, with no-progress / oscillation stops (→ D13).**
  A strong grounded model usually emits a runnable first draft (6/6 in test, repair never fired); a
  weaker model on hard prompts fails mostly at the **load tier** (lint-clean but unrunnable) and **one
  repair recovers most** (1/6 → 4/6, the entire achievable lift). Default **N = 2** (measured plateau
  0–1), short-circuit on success, and stop on **no-progress** (identical re-draft) / oscillation /
  budget. Feedback is lint-first (precise), then the dry-run one-line (the backstop).

## 1. Dry-run signal and tiering (Track A)

Measured on the committed `v2_corpus/` defect taxonomy (every dry-run-only class present) against a
real GMAT R2026a install with `gmat-run` 0.6, each dry-run isolated in its own subprocess.

| defect class | lint | load tier | run tier | first caught |
|---|---|---|---|---|
| `bad_eccentricity` (ECC > 1) | clean | **FAIL** | — | load |
| `bad_epoch` (bad Gregorian) | clean | **FAIL** | — | load |
| `missing_potential_file` | clean | **FAIL** | — | load |
| `undeclared_reference` (lint gap) | clean | **FAIL** | — | load |
| `infeasible_target` | clean | ok | **no-converge** | **run (convergence)** |
| `valid_propagate` | clean | ok | ok | — (clean through both) |
| `valid_target_converges` | clean | ok | ok (converged) | — (clean through both) |
| the 7 static classes (`unknown_*`, `type_mismatch`, …) | ERROR/WARNING | FAIL | — | lint (also load) |

**Per-tier wall-clock (seconds):**

| tier | min | med | max |
|---|---|---|---|
| GMAT bootstrap (1×/process) | 0.17 | 0.17 | 0.18 |
| load tier (`Mission.load`) | 0.15 | 0.16 | 0.17 |
| run tier (`mission.run`) | 0.04 | 0.06 | 0.16 |
| full subprocess (cold) | 0.82 | 0.86 | 1.03 |

**Findings.**

1. **The tiering claim (D5) holds empirically.** The load tier catches all four dry-run-only load
   defects (bad elements, bad epoch, missing data file, the undeclared reference lint misses); only
   **non-convergence** reaches the run tier. v0.2 should load-first and run only when a solver is
   present or a deeper check is wanted.
2. **Load is cheap; run is cheap-here-but-unbounded.** For these small missions `run` adds only tens
   of milliseconds, but a real differential corrector or optimiser can iterate for seconds to
   minutes — the reason the run tier sits behind a timeout and is gated on a solver being present.
3. **`Results.converged` is the convergence oracle, orthogonal to run success.** `infeasible_target`
   *runs* (`run_ok`) yet `converged == {"DC": False}` — "ran" is not "solved". The dry-run verdict
   must check both.

## 2. Error extraction: raw GMAT log → one actionable line

The repair signal is only as good as the line fed back. gmat-run exposes the error text two ways,
and they are asymmetric:

- **Run tier — rich.** `GmatRunError.log` carries the full GMAT run log; `Results.converged` names
  the solver(s) that failed. Distil directly.
- **Load tier — thin.** `GmatLoadError` is `"GMAT could not parse '<path>'; check the GMAT log file
  for the underlying error"` — no `.log`. The real cause (`**** ERROR **** …`) is written only to
  GMAT's log, which the default path does not retain through the API call. **Redirect it first** with
  `gmat.UseLogFile(<temp>)` before `Mission.load`, then read the temp log on failure.

A small regex then strips the sequence-number / script-path prefix and the trailing `in line:`
noise and keeps the `**** ERROR ****` / `Interpreter Exception:` message (warnings as a fallback). A
final path-sanitiser collapses any absolute path to its basename so neither the model feedback nor
this proof's output leaks a local path. Worked output:

| defect | distilled feedback line |
|---|---|
| `bad_epoch` | `Gregorian date "01 Foo 2025 12:00:00.000" is not valid.` |
| `bad_eccentricity` | `Utility Exception: The value of "1.5" for field "ECC" on object "Sat" is not an allowed value.` |
| `unknown_field` | `The field name "DryMas" on object "Sat" is not permitted` |
| `unknown_resource_type` | `Cannot create an object "Sat". The "Spcecraft" is an unknown object type …` |
| `missing_potential_file` | `ODEModel Exception Thrown: The file name "NoSuchFile.cof" does not exist` |
| `undeclared_reference` | `The ODEModel named "FM", referenced by the Propagator "Prop" cannot be found` |
| `infeasible_target` | `solver(s) DC did not converge` |

Each is a single, specific, actionable sentence — exactly what a repair prompt needs. **Upstream ask
(carry forward):** gmat-run could expose the load log on `GmatLoadError` (a `.log` like
`GmatRunError`), which would remove the `UseLogFile` dance; until then the dry-run owns the redirect.

## 3. Subprocess-isolation contract

- **Why.** gmatpy relies on one process-global Moderator; it cannot be reset between different
  scripts in one interpreter (confirmed by both gmat-sweep and astrodynamics-mcp, which isolate for
  the same reason). A repair loop that dry-runs several drafts therefore **must** spawn a fresh
  process per dry-run.
- **How.** The proof re-invokes itself (`--dryrun-one <script> --gmat-root <root>`) and passes the
  verdict back as one JSON line on stdout; a crash or non-JSON tail degrades to a `crash` verdict
  rather than taking down the loop. (The package's v0.2 validator can use the same shape — a worker
  module with a pickled/JSON spec+result, as gmat-sweep and astrodynamics-mcp do.)
- **Cost.** ~0.8–1.0 s cold per dry-run (above). A **300 s timeout** bounds a runaway solver and is
  recorded as a failure verdict.
- **gmat_root.** `Mission.load` honours `--gmat-root` / `GMAT_ROOT` via `locate_gmat`; discovery
  happens inside the worker, so the subprocess must see the same environment.

## 4. Repair-loop convergence (Track B)

The real `draft` → lint → dry-run → repair loop, run on two providers to span the quality range. The
repair prompt is the original intent + the failing draft + the failing tier's diagnostics; the loop
short-circuits on the first runnable draft. (Only GitHub Models was reachable — see the caveat.)

**Strong grounded model — `gpt-4.1-mini`, 6 prompts (easy → hard).** **6/6 pass on the initial
draft**; the repair loop never fired (a flat 6/6 from attempt 0), and both hard targeting prompts
converged first try. A strong model grounded by the RAG context usually emits a lint-clean, runnable
first draft — **repair is a backstop, not the hot path.**

**Weaker model on harder prompts — `gpt-4o-mini`, 6 hard/exotic prompts.** This populates the failure
regime the loop exists for:

| prompt | outcome | pass@ | per-attempt tier |
|---|---|---|---|
| `sun_earth_l2` | pass | 0 | clean |
| `hohmann_transfer_target` | pass | 1 | load → clean |
| `finite_burn_target_sma` | pass | 1 | load → clean |
| `geo_stationkeeping` | pass | 1 | load → clean |
| `bplane_target` | fail | — | load × 4 (unrepaired in budget) |
| `optimize_transfer_dv` | fail | — | load × 4 (**no-progress**: identical re-draft) |

Convergence curve (cumulative runnable):

| attempt | runnable |
|---|---|
| 0 (initial) | 1/6 |
| 1 (repair 1) | **4/6** |
| 2 (repair 2) | 4/6 |
| 3 (repair 3) | 4/6 |

**Findings.**

1. **Repair works, and the lift is front-loaded.** 1/6 → 4/6 after a *single* repair; repairs 2–3 add
   nothing on this sample — the first repair captures the entire achievable gain.
2. **Every initial failure here was load-tier** — lint-clean scripts GMAT's loader rejected (the
   dry-run-only gap). v0.1's lint gate alone would have passed them; the dry-run is what caught them,
   and the distilled load-tier one-line is what the model fixed. This is the close-the-loop win,
   demonstrated end-to-end.
3. **Stop conditions are load-bearing.** `optimize_transfer_dv` hit **no-progress** (re-emitted an
   identical broken draft); `bplane_target` never converged in budget. The loop must stop on an
   identical re-draft (script-hash match) and on budget exhaustion rather than pay for attempts that
   cannot improve. (No oscillation in this sample; the detector is in place for it.)
4. **The budget plateaus fast.** Measured plateau N = 1 (weak model), 0 (strong model). The default
   should be **N = 2**: one repair does the work, a second covers prompt-distribution variance, and
   beyond that no-progress / persistent failure dominate, so a larger budget only burns tokens.

## Diagnostic reconciliation (→ D12)

Dry-run findings **extend the same severity intent** as lint (a failure blocks; convergence-failure
blocks) but **do not share the `LintReport` shape**. Lint diagnostics are precise (rule, severity,
line, column); dry-run findings are a coarser `{tier, ok, converged, one_line, raw_log}`. They sit
in a **separate `dry_run` tier** on the result, consumed in order: lint blocking-diagnostics first
(strict mode rejects on ERROR + WARNING per D5), and only if lint is clean does the dry-run run and
contribute its one-line. The repair loop feeds whichever tier failed. This keeps the v0.1 lint
contract unchanged and makes the dry-run a strictly additive backstop.

## Decisions to record (→ design freeze)

**D12 — gmat-run dry-run integration contract.** The v0.2 dry-run is a tiered gmat-run call behind
the `[gmat]` extra: `Mission.load` (config tier) then `mission.run` + `Results.converged`
(execution tier, gated on a solver and a 300 s timeout). Each dry-run runs in a fresh subprocess
(gmatpy single-Moderator limit). Error extraction is asymmetric: run-tier from `GmatRunError.log` /
`Results.converged`; load-tier via a `gmat.UseLogFile()` redirect read back on `GmatLoadError`
(thin, no `.log`), both distilled to one actionable, path-free line. Findings land in a separate
`dry_run` result tier, not the `LintReport`; the dry-run runs only on lint-clean scripts.

**D13 — repair loop.** v0.2 wraps generation in a bounded repair loop: generate → lint → (if clean)
dry-run → on failure regenerate with a repair prompt = original intent + the failing draft + the
failing tier's diagnostics. **Default retry budget N = 2** (measured plateau 0–1; the first repair
captures most of the lift, 1/6 → 4/6 on the weak-model sample). The loop **stops** on the first
runnable draft, on an identical re-draft (no-progress, by script hash), on a repeated earlier draft
(oscillation), or on budget exhaustion. Feedback is lint-first (precise rule/line) then the dry-run
one-line — the backstop that catches the lint-clean-but-unrunnable drafts the loop exists for.

## Proof

Harness: [`v5_close_loop_proof.py`](./v5_close_loop_proof.py). Two tracks: **Track A** (deterministic
tiering, per-tier cost, and the log→one-line extraction over `v2_corpus/`; needs only a GMAT
install) and **Track B** (the real `draft` → lint → dry-run → repair loop over an eval-prompt subset;
needs a reachable provider, **skipped gracefully** when none is configured, so the file is
re-runnable anywhere).

```
# both tracks (real inference + real GMAT):
GH_TOKEN=$(gh auth token) uv run --with 'gmat-run>=0.6' python v5_close_loop_proof.py \
    --gmat-root ~/gmat-R2026a --model github:openai/gpt-4.1-mini

# deterministic tiering/extraction only (no inference):
uv run --with 'gmat-run>=0.6' python v5_close_loop_proof.py --gmat-root ~/gmat-R2026a --corpus-only
```

Run with `uv run --with 'gmat-run>=0.6'` so the committed env stays GMAT-free; `GMAT_ROOT` also
works in place of `--gmat-root`. Verified on R2026a with `gmat-run` 0.6 (Python 3.12).

**Caveat (provider breadth).** Only GitHub Models was reachable here, so Track B spans two
GitHub-hosted models (`gpt-4.1-mini`, `gpt-4o-mini`) rather than true cross-vendor providers
(Anthropic / Ollama). That fixes the *mechanism* — repair converges, the lift is front-loaded, the
stop conditions fire — and the small-N recommendation; the absolute pass-rates are model- and
prompt-subset-specific, and the eval suite / leaderboard is where per-model numbers are tracked.
(Mirrors V2's real-model caveat: the spike fixes capability and contract, not frequency.)
