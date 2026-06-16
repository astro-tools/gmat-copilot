"""V2 spike proof: gmat-script lint vs gmat-run dry-run coverage over a defect taxonomy.

For each `.script` in `v2_corpus/`, run the static gmat-script linter and a real gmat-run
dry-run (load tier + run tier), and report which tier first catches each defect. Settles the
strict/permissive validation contract and the v0.1 (lint-only) / v0.2 (lint + dry-run) split,
recorded as D5.

The corpus is a hand-crafted defect taxonomy: an LLM was not available to generate real model
output in this environment, so each script deliberately isolates one defect class via a
`% DEFECT:` / `% EXPECT:` header. This fixes the *capability* mapping (which classes are
static-catchable vs dry-run-only) precisely; the real-model error *frequency* is deferred to
the eval suite.

Run::

    python v2_validation_proof.py --gmat-root /path/to/gmat-install

(`GMAT_ROOT` also works.) Each script's dry-run runs in its own subprocess for crash isolation
and to avoid the in-process gmatpy re-init limit. Internal worker mode: `--dryrun-one <script>`.

Dependencies: gmat-script, gmat-run (+ a GMAT install for the dry-run). Not base deps — install
in a throwaway environment to run this spike.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CORPUS = Path(__file__).parent / "v2_corpus"
DRYRUN_TIMEOUT_S = 300


def read_header(path: Path) -> tuple[str, str]:
    defect, expect = "?", "?"
    for line in path.read_text(encoding="utf-8").splitlines()[:8]:
        s = line.strip()
        if s.startswith("% DEFECT:"):
            defect = s.split(":", 1)[1].strip()
        elif s.startswith("% EXPECT:"):
            expect = s.split(":", 1)[1].strip()
    return defect, expect


def run_lint(path: Path) -> dict:
    from gmat_script import Severity, lint

    diags = lint(path.read_text(encoding="utf-8"))
    order = {Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1}
    sev = max((d.severity for d in diags), key=lambda s: order[s]).name if diags else None
    return {"rules": sorted({d.rule for d in diags}), "severity": sev, "n": len(diags)}


def dryrun_one(script: Path, gmat_root: str) -> dict:
    """Worker: load + run one script through gmat-run; return the outcome."""
    from gmat_run import GmatError, Mission

    out: dict = {"load_ok": False, "run_ok": False, "converged": None, "err": None}
    try:
        with tempfile.TemporaryDirectory() as wd:
            mission = Mission.load(script, gmat_root=gmat_root)
            out["load_ok"] = True
            result = mission.run(working_dir=wd, overwrite=True)
            out["run_ok"] = True
            conv = result.converged
            out["converged"] = (all(conv.values()) if conv else None)
    except GmatError as e:
        out["err"] = f"{type(e).__name__}: {' '.join(str(e).split())[:180]}"
    except Exception as e:  # noqa: BLE001 — surface anything as data
        out["err"] = f"{type(e).__name__}: {' '.join(str(e).split())[:180]}"
    return out


def first_caught(lint_r: dict, dr: dict) -> str:
    if lint_r["severity"] == "ERROR":
        return "lint"
    if dr.get("load_ok") is False:
        return "load"
    if dr.get("run_ok") is False:
        return "run"
    if dr.get("converged") is False:
        return "run(no-converge)"
    return "—"


def main() -> None:
    ap = argparse.ArgumentParser(description="V2 lint-vs-dry-run coverage proof.")
    ap.add_argument("--gmat-root", default=os.environ.get("GMAT_ROOT", ""))
    ap.add_argument("--dryrun-one", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.dryrun_one:
        print(json.dumps(dryrun_one(Path(args.dryrun_one), args.gmat_root)))
        return

    if not args.gmat_root:
        sys.exit("pass --gmat-root /path/to/gmat-install or set GMAT_ROOT")
    scripts = sorted(CORPUS.glob("*.script"))
    if not scripts:
        sys.exit(f"no corpus scripts under {CORPUS}")

    rows = []
    for s in scripts:
        defect, expect = read_header(s)
        lint_r = run_lint(s)
        proc = subprocess.run(
            [sys.executable, __file__, "--dryrun-one", str(s), "--gmat-root", args.gmat_root],
            capture_output=True, text=True, timeout=DRYRUN_TIMEOUT_S,
        )
        try:
            dr = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:
            dr = {"load_ok": None, "run_ok": None, "converged": None,
                  "err": "no worker output: " + (proc.stderr.strip()[-160:] or "?")}
        rows.append((s.name, defect, expect, lint_r, dr))

    # table
    print(f"{'script':28} {'defect class':22} {'lint':30} {'load':5} {'run':5} {'conv':5} {'first-caught':16}")
    print("-" * 120)
    for name, defect, _expect, lr, dr in rows:
        lint_s = (f"{lr['severity'] or 'clean':7} " + ",".join(lr["rules"]))[:30]
        load = {True: "ok", False: "FAIL", None: "?"}[dr.get("load_ok")]
        run = {True: "ok", False: "FAIL", None: "?"}[dr.get("run_ok")]
        conv = {True: "yes", False: "NO", None: "—"}[dr.get("converged")]
        print(f"{name:28} {defect:22} {lint_s:30} {load:5} {run:5} {conv:5} {first_caught(lr, dr):16}")

    # summary
    static = [r for r in rows if r[2] == "lint"]
    dryonly = [r for r in rows if r[2] in ("load", "run")]
    valid = [r for r in rows if r[2] == "valid"]
    lint_caught_static = [r for r in static if r[3]["n"] > 0]
    lint_error_static = [r for r in static if r[3]["severity"] == "ERROR"]
    warn_but_hard = [r for r in rows
                     if r[3]["severity"] in ("WARNING", "INFO") and r[4].get("load_ok") is False]
    clean_but_fail = [r for r in rows
                      if r[3]["n"] == 0 and (r[4].get("load_ok") is False
                                             or r[4].get("run_ok") is False
                                             or r[4].get("converged") is False)]
    false_pos = [r for r in valid if r[3]["n"] > 0 or r[4].get("err")]

    print("\n=== summary ===")
    print(f"static-defect scripts            : {len(static)}")
    print(f"  flagged by lint (any severity) : {len(lint_caught_static)}/{len(static)}")
    print(f"  flagged by lint as ERROR       : {len(lint_error_static)}/{len(static)}")
    print(f"lint WARNING/INFO that GMAT rejects at load (→ strict should reject on these): {len(warn_but_hard)}")
    for r in warn_but_hard:
        print(f"    - {r[0]}  ({','.join(r[3]['rules'])})")
    print(f"lint-clean but dry-run fails (dry-run-only defects): {len(clean_but_fail)}/{len(dryonly)} expected")
    for r in clean_but_fail:
        print(f"    - {r[0]}  [{first_caught(r[3], r[4])}]  {r[4].get('err') or ('no-converge' if r[4].get('converged') is False else '')}")
    print(f"valid controls clean through both tiers: {len(valid) - len(false_pos)}/{len(valid)}")


if __name__ == "__main__":
    main()
