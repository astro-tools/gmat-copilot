"""V5 spike proof: gmat-run dry-run signal + repair-loop convergence (close the loop).

Settles the two open questions behind v0.2's "close the loop":

(A) **Dry-run signal + tiering.** For the lint-clean-but-broken corpus, dry-run each script
    through gmat-run in an isolated subprocess, timing the ``Mission.load`` (config) tier and the
    ``mission.run`` (execution + convergence) tier *separately*, and distil the raw GMAT log into a
    single actionable feedback line. Confirms D5's tiering claim empirically and demonstrates the
    error-extraction the repair loop needs.

(B) **Repair convergence.** Over a handful of real eval prompts, generate with a real provider via
    the package's own ``draft``, then run a bounded repair loop that feeds the combined lint +
    dry-run diagnostics back and regenerates, recording the per-retry pass-rate, the plateau retry
    budget N, and any oscillation / no-progress.

Two tracks so the deterministic numbers (A) do not depend on a model happening to fail, and the
real-model numbers (B) are honest tool output:

* Track A runs on the committed ``v2_corpus/`` defect taxonomy (every dry-run-only class present),
  with per-tier wall-clock and per-subprocess process cost. Deterministic; needs only a GMAT install.
* Track B runs the real ``draft`` → lint → dry-run → repair loop on a prompt subset. Needs a
  reachable provider; **skipped gracefully** when none is configured (like the V2 proof's
  LLM-unavailable fallback), so this file is re-runnable in any environment.

Run::

    # both tracks (real inference + real GMAT):
    GH_TOKEN=$(gh auth token) python v5_close_loop_proof.py \
        --gmat-root ~/gmat-R2026a --model github:openai/gpt-4.1-mini

    # deterministic tiering/extraction track only (no inference):
    python v5_close_loop_proof.py --gmat-root ~/gmat-R2026a --corpus-only

``GMAT_ROOT`` also works in place of ``--gmat-root``. Each dry-run runs in its own subprocess for
crash isolation and to dodge the in-process gmatpy single-Moderator re-init limit (the gmat-sweep /
astrodynamics-mcp pattern). Internal worker mode: ``--dryrun-one <script>``.

Dependencies: gmat-script (the lint half, a base dep), gmat-run + a GMAT install (the dry-run half,
the ``[gmat]`` extra), and a provider credential for Track B. The dry-run + provider deps are not
base deps — run with ``uv run --with 'gmat-run>=0.6' …`` so the committed env stays clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
V2_CORPUS = HERE / "v2_corpus"
PROMPTS = HERE.parent.parent.parent / "tests" / "data" / "eval" / "prompts.json"

DRYRUN_TIMEOUT_S = 300
DEFAULT_RETRY_BUDGET = 3
# A subset of the eval set chosen to exercise the dry-run-only failure tiers a real model trips:
# an easy control expected to run clean, an epoch/format case (load tier), a gravity-field case that
# may want a potential file (load tier), tank+thruster wiring (load/run tier), and two solver cases
# (run tier — convergence). Spans easy→hard and both dry-run tiers.
DEFAULT_PROMPT_IDS = (
    "leo_circular",
    "set_epoch_utc",
    "nonspherical_gravity",
    "finite_burn",
    "target_apogee",
    "hohmann_transfer_target",
)


# --------------------------------------------------------------------------- raw-log → one line

# Distil a raw GMAT log / gmat-run error into one actionable feedback line. Adapted from the
# astrodynamics-mcp log scraper: GMAT emits its substantive cause as an "Interpreter Exception:" or a
# "*** ERROR ***" line, optionally prefixed with the script path and suffixed with "in line:". We
# strip the noise and keep the first substantive error line; warnings are a fallback.
_PATH_PREFIX_RE = re.compile(r"^[^:\n]*\.script:\s*", re.IGNORECASE)
_SEQNO_PREFIX_RE = re.compile(r"^\d+:\s+\S+:\s+")
_ERROR_RE = re.compile(r"\*+\s*ERROR\s*\*+\s*(?:Interpreter\s+Exception:\s*)?(?P<msg>.+?)\s*$")
_INTERP_RE = re.compile(r"Interpreter\s+Exception:\s*(?P<msg>.+?)\s*$")
_WARNING_RE = re.compile(r"\*+\s*WARNING\s*\*+\s*(?P<msg>.+?)\s*$")
_IN_LINE_SUFFIX_RE = re.compile(r"\s+in\s+line:?\s*$")
# Final guard: collapse any absolute path ending in a known artefact to its basename, so a feedback
# line (or this proof's printed output, which the write-up quotes) never leaks a local filesystem path.
_ABS_PATH_RE = re.compile(r"/[\w./ -]+/([\w.-]+\.(?:script|txt|log))")


def strip_paths(text: str) -> str:
    """Replace any absolute path to a ``.script``/``.txt``/``.log`` with its basename."""
    return _ABS_PATH_RE.sub(r"\1", text)


def extract_feedback_line(raw: str) -> str:
    """Return one actionable line from a raw GMAT log or gmat-run error string.

    Prefers the first substantive ERROR / Interpreter-Exception line; falls back to the first
    WARNING, then to the first non-blank line. Strips the script-path prefix, the sequence-number
    prefix, and the trailing ``in line:`` noise GMAT appends.
    """
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    warning: str | None = None
    for ln in lines:
        bare = _SEQNO_PREFIX_RE.sub("", ln)
        bare = _PATH_PREFIX_RE.sub("", bare)
        for rx in (_ERROR_RE, _INTERP_RE):
            m = rx.search(bare)
            if m:
                return strip_paths(_IN_LINE_SUFFIX_RE.sub("", m.group("msg")).strip())
        if warning is None:
            mw = _WARNING_RE.search(bare)
            if mw:
                warning = strip_paths(_IN_LINE_SUFFIX_RE.sub("", mw.group("msg")).strip())
    if warning:
        return warning
    first = _PATH_PREFIX_RE.sub("", _SEQNO_PREFIX_RE.sub("", lines[0]))
    return strip_paths(first)[:200]


# --------------------------------------------------------------------------- dry-run worker

def dryrun_one(script: Path, gmat_root: str) -> dict:
    """Worker: bootstrap once, then load (config tier) and run (execution tier) through gmat-run.

    Times the one-time GMAT **bootstrap**, the **load** tier, and the **run** tier separately, and
    captures the raw GMAT error text so the parent can both report per-tier wall-clock and distil one
    actionable feedback line. Runs in its own process (see ``run_dryrun``) for crash isolation and the
    gmatpy single-Moderator re-init limit.

    The GMAT log is redirected to a temp file *before* loading: gmat-run's ``GmatLoadError`` is thin
    ("could not parse '<path>'; check the GMAT log") and carries no ``.log``, so the load-tier cause
    only exists in the redirected log. Run-tier failures instead carry the log on ``GmatRunError.log``.
    """
    import tempfile

    from gmat_run import Mission
    from gmat_run.install import locate_gmat
    from gmat_run.runtime import bootstrap

    try:  # gmat-run's base exception; GmatRunError carries the run log on ``.log``
        from gmat_run import GmatError
    except ImportError:  # very old gmat-run
        GmatError = Exception  # type: ignore[assignment,misc]

    out: dict = {
        "bootstrap_s": None, "load_ok": False, "load_s": None,
        "run_ok": False, "run_s": None,
        "converged": None, "tier": None, "raw": "", "one_line": "",
    }
    with tempfile.TemporaryDirectory() as wd:
        load_log = Path(wd) / "gmat_load.log"
        tb = time.perf_counter()
        gmat = bootstrap(locate_gmat(gmat_root))
        try:  # redirect the GMAT log so a load-tier parse error is recoverable
            gmat.UseLogFile(str(load_log))
        except Exception:  # pragma: no cover - older gmatpy may lack it
            pass
        out["bootstrap_s"] = round(time.perf_counter() - tb, 3)

        try:
            t0 = time.perf_counter()
            mission = Mission.load(script, gmat_root=gmat_root)
            out["load_s"] = round(time.perf_counter() - t0, 3)
            out["load_ok"] = True
        except Exception as e:  # noqa: BLE001 - surface as data, not a crash
            out["tier"] = "load"
            out["raw"] = _load_text(e, load_log)
            out["one_line"] = extract_feedback_line(out["raw"])
            return out

        try:
            t1 = time.perf_counter()
            result = mission.run(working_dir=wd, overwrite=True)
            out["run_s"] = round(time.perf_counter() - t1, 3)
            out["run_ok"] = True
            conv = result.converged
            out["converged"] = (all(conv.values()) if conv else None)
            if out["converged"] is False:
                failed = sorted(name for name, ok in conv.items() if not ok)
                out["tier"] = "run(no-converge)"
                out["one_line"] = f"solver(s) {', '.join(failed)} did not converge"
        except GmatError as e:  # noqa: BLE001
            out["tier"] = "run"
            out["raw"] = _err_text(e)
            out["one_line"] = extract_feedback_line(out["raw"])
    return out


def _err_text(e: BaseException) -> str:
    """The richest available text from a run-tier error: the raw GMAT ``.log`` if present, else str."""
    log = getattr(e, "log", None)
    if isinstance(log, str) and log.strip():
        return log
    return f"{type(e).__name__}: {e}"


def _load_text(e: BaseException, load_log: Path) -> str:
    """Load-tier text: the redirected GMAT log (the real parse cause) if it captured an error.

    gmat-run's ``GmatLoadError`` only says "could not parse '<path>'", so fall back to the redirected
    log, which holds GMAT's actual ``**** ERROR ****`` line. If neither is informative, use ``str``.
    """
    if load_log.exists():
        text = load_log.read_text(encoding="utf-8", errors="replace")
        if "ERROR" in text or "Exception" in text:
            return text
    return f"{type(e).__name__}: {e}"


def run_dryrun(script_path: Path, gmat_root: str) -> dict:
    """Dry-run *script_path* in a fresh subprocess; return the worker dict + total process cost."""
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, __file__, "--dryrun-one", str(script_path), "--gmat-root", gmat_root],
        capture_output=True, text=True, timeout=DRYRUN_TIMEOUT_S,
    )
    proc_s = round(time.perf_counter() - t0, 3)
    try:
        dr = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        dr = {"load_ok": None, "run_ok": None, "converged": None, "tier": "crash",
              "raw": proc.stderr.strip()[-200:], "one_line": "worker produced no output",
              "load_s": None, "run_s": None}
    dr["proc_s"] = proc_s
    return dr


# --------------------------------------------------------------------------- lint

def lint_summary(script: str) -> dict:
    """Lint *script* and return a compact summary + the diagnostics as feedback lines."""
    from gmat_script import Severity, lint

    order = {Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1}
    diags = lint(script)
    blocking = [d for d in diags if d.severity in (Severity.ERROR, Severity.WARNING)]
    sev = max((d.severity for d in diags), key=lambda s: order[s]).name if diags else None
    lines = [
        f"{d.severity.name.lower()} [{d.rule}] line {d.start.line}: {d.message}" for d in blocking
    ]
    return {"severity": sev, "n": len(diags), "n_blocking": len(blocking), "lines": lines,
            "clean": not blocking}


def script_id(script: str) -> str:
    return hashlib.sha256(script.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- track A: tiering

def header(path: Path) -> tuple[str, str]:
    defect, expect = "?", "?"
    for line in path.read_text(encoding="utf-8").splitlines()[:8]:
        s = line.strip()
        if s.startswith("% DEFECT:"):
            defect = s.split(":", 1)[1].strip()
        elif s.startswith("% EXPECT:"):
            expect = s.split(":", 1)[1].strip()
    return defect, expect


def track_a(gmat_root: str) -> None:
    """Deterministic tiering + extraction over the V2 defect corpus."""
    scripts = sorted(V2_CORPUS.glob("*.script"))
    if not scripts:
        sys.exit(f"no corpus scripts under {V2_CORPUS}")
    print("\n=== Track A — dry-run tiering, per-tier cost, and one-line extraction (V2 corpus) ===\n")
    print(f"{'script':26} {'expect':6} {'lint':8} {'load':>7} {'run':>7} {'proc':>7} "
          f"{'first-tier':16} one-line")
    print("-" * 130)
    boot_times, load_times, run_times, proc_times = [], [], [], []
    for s in scripts:
        _defect, expect = header(s)
        ls = lint_summary(s.read_text(encoding="utf-8"))
        dr = run_dryrun(s, gmat_root)
        if dr.get("bootstrap_s") is not None:
            boot_times.append(dr["bootstrap_s"])
        if dr.get("load_s") is not None:
            load_times.append(dr["load_s"])
        if dr.get("run_s") is not None:
            run_times.append(dr["run_s"])
        if dr.get("proc_s") is not None:
            proc_times.append(dr["proc_s"])
        load = _fmt(dr.get("load_s"), dr.get("load_ok"))
        run = _fmt(dr.get("run_s"), dr.get("run_ok"))
        proc = f"{dr.get('proc_s'):.1f}s" if dr.get("proc_s") is not None else "?"
        tier = dr.get("tier") or ("—" if dr.get("run_ok") else "?")
        print(f"{s.name:26} {expect:6} {ls['severity'] or 'clean':8} {load:>7} {run:>7} {proc:>7} "
              f"{tier:16} {dr.get('one_line', '')[:48]}")
    print("\n--- per-tier wall-clock (seconds) ---")
    _stat("GMAT bootstrap (1x/process)", boot_times)
    _stat("load tier (Mission.load)   ", load_times)
    _stat("run  tier (mission.run)    ", run_times)
    _stat("full subprocess (cold)     ", proc_times)


def _fmt(secs: float | None, ok: bool | None) -> str:
    if secs is None:
        return "FAIL" if ok is False else "?"
    return f"{secs:.2f}s"


def _stat(label: str, xs: list[float]) -> None:
    if not xs:
        print(f"  {label}: (none)")
        return
    xs = sorted(xs)
    print(f"  {label}: n={len(xs)} min={xs[0]:.2f} med={xs[len(xs) // 2]:.2f} max={xs[-1]:.2f}")


# --------------------------------------------------------------------------- track B: repair loop


def repair_request(original: str, prev_script: str, feedback: list[str]) -> str:
    """The repair-prompt shape: the original intent + the failing draft + the diagnostics to fix.

    A faithful proxy for the v0.2 repair prompt — it reuses the real ``draft`` pipeline (system
    framing, retrieval, output contract) and only augments the request with the prior attempt and
    its combined lint + dry-run feedback.
    """
    bullets = "\n".join(f"- {ln}" for ln in feedback)
    return (
        f"{original}\n\n"
        "A previous attempt produced the script below, but it failed validation. Return a "
        "corrected, complete script that fixes every problem listed.\n\n"
        f"```script\n{prev_script}\n```\n\n"
        f"Problems to fix:\n{bullets}"
    )


def evaluate(script: str, gmat_root: str) -> dict:
    """Lint, then (only if lint-clean, per the tiered D5 contract) dry-run. Return the verdict."""
    ls = lint_summary(script)
    verdict = {"lint": ls, "dry": None, "passed": False, "feedback": [], "feedback_tier": None}
    if not ls["clean"]:
        verdict["feedback"] = ls["lines"]
        verdict["feedback_tier"] = "lint"
        return verdict
    dr = run_dryrun_text(script, gmat_root)
    verdict["dry"] = dr
    runnable = dr.get("load_ok") and dr.get("run_ok") and dr.get("converged") is not False
    if runnable:
        verdict["passed"] = True
    else:
        verdict["feedback"] = [dr.get("one_line") or "dry-run failed"]
        verdict["feedback_tier"] = dr.get("tier") or "dry-run"
    return verdict


def run_dryrun_text(script: str, gmat_root: str) -> dict:
    """Write *script* to a temp file and dry-run it in a subprocess."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "draft.script"
        p.write_text(script, encoding="utf-8")
        return run_dryrun(p, gmat_root)


def track_b(args: argparse.Namespace) -> None:
    """Real-model generation + bounded repair loop over a prompt subset."""
    try:
        from gmat_copilot import draft
        from gmat_copilot.eval.prompts import load_prompts
        from gmat_copilot.providers import ProviderError, reachable_providers
        from gmat_copilot.rag import Retriever
    except ImportError as e:
        print(f"\n=== Track B skipped — gmat_copilot not importable ({e}) ===")
        return

    if not args.model:
        reach = reachable_providers()
        print(f"\n=== Track B skipped — no --model given (reachable now: {reach or 'none'}) ===")
        return

    prompts = {p.id: p for p in load_prompts(PROMPTS)}
    ids = tuple(i.strip() for i in args.prompt_ids.split(",")) if args.prompt_ids else DEFAULT_PROMPT_IDS
    chosen = [prompts[i] for i in ids if i in prompts][: args.max_prompts]
    print(f"\n=== Track B — repair-loop convergence ({args.model}, retry budget "
          f"N={args.retry_budget}, {len(chosen)} prompts) ===\n")

    retriever = Retriever()  # load the embedder once; reused across every draft
    budget = args.retry_budget
    # passed_at[i] = attempt index (0 = first try) a prompt first passed, else None
    passed_at: list[int | None] = []
    rows: list[dict] = []

    for prompt in chosen:
        history: list[str] = []  # script ids, to spot no-progress / oscillation
        request = prompt.request
        note = ""
        outcome = "fail"
        first_pass: int | None = None
        attempts_trace: list[str] = []
        for attempt in range(budget + 1):  # attempt 0 = initial draft, then up to `budget` repairs
            try:
                result = draft(request, model=args.model, strict=False, retriever=retriever,
                               max_tokens=3072)
            except ProviderError as e:
                note = f"provider error at attempt {attempt}: {str(e)[:80]}"
                outcome = "provider-error"
                break
            sid = script_id(result.script)
            if attempt > 0 and sid == history[-1]:
                note = f"no-progress (identical re-draft) at attempt {attempt}"
            elif sid in history:
                note = f"oscillation (defect reintroduced) at attempt {attempt}"
            history.append(sid)

            verdict = evaluate(result.script, args.gmat_root)
            tier = "clean" if verdict["passed"] else (verdict["feedback_tier"] or "?")
            attempts_trace.append(tier)
            if verdict["passed"]:
                first_pass = attempt
                outcome = "pass"
                break
            request = repair_request(prompt.request, result.script, verdict["feedback"])
        passed_at.append(first_pass)
        rows.append({"id": prompt.id, "difficulty": prompt.difficulty, "outcome": outcome,
                     "first_pass": first_pass, "trace": attempts_trace, "note": note})

    # per-prompt table
    print(f"{'prompt':26} {'diff':7} {'outcome':14} {'pass@':>6}  trace (per-attempt feedback tier)")
    print("-" * 110)
    for r in rows:
        pa = "—" if r["first_pass"] is None else f"#{r['first_pass']}"
        trace = " → ".join(r["trace"]) + (f"   [{r['note']}]" if r["note"] else "")
        print(f"{r['id']:26} {r['difficulty']:7} {r['outcome']:14} {pa:>6}  {trace}")

    # cumulative pass-rate curve
    n = len(rows)
    print("\n--- cumulative pass-rate by attempt (the convergence curve) ---")
    for k in range(budget + 1):
        passed = sum(1 for pa in passed_at if pa is not None and pa <= k)
        label = "initial draft" if k == 0 else f"after repair {k}"
        print(f"  attempt {k} ({label:14}): {passed}/{n}  {'#' * passed}")
    first_passes = [pa for pa in passed_at if pa is not None]
    final = len(first_passes)
    initial = sum(1 for pa in passed_at if pa == 0)
    needed_n = max(first_passes, default=0)
    print(f"\ninitial-draft pass: {initial}/{n}; after repair: {final}/{n} runnable.")
    print(f"all achievable passes captured by attempt {needed_n} "
          f"→ recommended default retry budget N = {needed_n} "
          f"({'no repair lifted any draft' if needed_n == 0 and final else f'+{final - initial} from repair'}).")


def main() -> None:
    ap = argparse.ArgumentParser(description="V5 close-the-loop spike proof.")
    ap.add_argument("--gmat-root", default=os.environ.get("GMAT_ROOT", ""))
    ap.add_argument("--model", default=None, help="provider:model for Track B (e.g. github:openai/gpt-4.1-mini)")
    ap.add_argument("--retry-budget", type=int, default=DEFAULT_RETRY_BUDGET)
    ap.add_argument("--max-prompts", type=int, default=len(DEFAULT_PROMPT_IDS))
    ap.add_argument("--prompt-ids", default=None,
                    help="comma-separated eval-prompt ids for Track B (default: the built-in subset)")
    ap.add_argument("--corpus-only", action="store_true", help="Track A only (no inference)")
    ap.add_argument("--skip-track-a", action="store_true", help="Track B only (skip the deterministic track)")
    ap.add_argument("--dryrun-one", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.dryrun_one:
        print(json.dumps(dryrun_one(Path(args.dryrun_one), args.gmat_root)))
        return

    if not args.gmat_root:
        sys.exit("pass --gmat-root /path/to/gmat-install or set GMAT_ROOT")

    if not args.skip_track_a:
        track_a(args.gmat_root)
    if not args.corpus_only:
        track_b(args)


if __name__ == "__main__":
    main()
