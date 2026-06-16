"""V3 spike proof: eval protocol — structural scorer + LLM-as-judge accuracy/reproducibility.

For each pilot prompt (`v3_prompts/prompts.json`) and its candidate scripts, this:

1. runs the **deterministic structural scorer** (gmat-script): lint <= INFO per D5, plus the
   golden's required resource types / fields / commands — settling the cases it can;
2. runs an **LLM-as-judge** (GitHub Models, free tier, via `gh auth token`) on the candidates
   that pass structurally, M times per (candidate, model), and measures
   - **accuracy** = majority verdict vs the authored/Opus gold label, and
   - **reproducibility** = run-to-run verdict self-agreement;
3. records every verdict to a fixtures file so the same scoring **replays deterministically**
   with no model call — the per-merge CI path.

The gold labels are authored (each candidate is built as intent-satisfying or not) and serve as
the one-time, frozen, high-quality reference (the "judge it once with the strongest judge"
pattern). The CI-reachable small models are graded against that gold.

Run (live judge)::

    python v3_eval_proof.py --gmat-root <gmat-install>          # uses `gh auth token`

Replay (deterministic, no model)::

    python v3_eval_proof.py --replay v3_judge_fixtures.json

Deps: gmat-script (+ a GMAT install only so gmat-script resolves the same catalogue version;
the structural checks are GMAT-free). The judge uses stdlib urllib against
https://models.github.ai/inference. Not base deps — install in a throwaway env.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
PROMPTS = HERE / "v3_prompts" / "prompts.json"
CAND_DIR = HERE / "v3_prompts" / "candidates"
FIXTURES = HERE / "v3_judge_fixtures.json"
ENDPOINT = "https://models.github.ai/inference/chat/completions"

# CI-reachable free-tier judges. M = repeats for the reproducibility measurement; sized to the
# Free-plan daily caps (Low 150/day shared, High 50/day) — see the writeup.
MODELS = [
    {"id": "openai/gpt-4.1-mini", "tier": "Low", "M": 6},
    {"id": "openai/gpt-4o-mini", "tier": "Low", "M": 3},
    {"id": "openai/gpt-4.1", "tier": "High", "M": 3},
]
PACE_S = {"Low": 4.5, "High": 6.5}  # >= per-minute tier budget

JUDGE_SYSTEM = (
    "You are a strict evaluator of GMAT mission scripts. Given a natural-language INTENT and a "
    "candidate GMAT .script, decide whether the script satisfies the intent. Judge ONLY against "
    "the intent and ignore stylistic differences. A script that is syntactically valid but models "
    "the wrong orbit, wrong inclination, wrong quantity, wrong maneuver direction, wrong target "
    "value, or wrong output format does NOT satisfy the intent. Respond with ONLY a JSON object: "
    '{"satisfies_intent": true or false, "reason": "<one short sentence>"}.'
)


# ---------------- structural scorer (deterministic, gmat-script) ----------------
def _all_command_keywords(script) -> list[str]:
    kws: list[str] = []

    def walk(cmds):
        for c in cmds:
            kws.append(getattr(c, "keyword", ""))
            body = getattr(c, "body", None)
            if body:
                walk(body)

    walk(script.mission_sequence)
    return kws


def structural_score(text: str, spec: dict) -> dict:
    from gmat_script import Script, Severity, lint

    fails: list[str] = []
    diags = lint(text)
    blocking = [d for d in diags if d.severity in (Severity.ERROR, Severity.WARNING)]
    if blocking:
        fails.append("lint:" + ",".join(sorted({d.rule for d in blocking})))

    script = Script.parse(text)
    present_types = {r.type for r in script.resources.values()}
    for t in spec.get("required_types", []):
        if t not in present_types:
            fails.append(f"missing-type:{t}")
    for t, fields in spec.get("required_fields", {}).items():
        res = [r for r in script.resources.values() if r.type == t]
        for f in fields:
            if not any(f in r for r in res):
                fails.append(f"missing-field:{t}.{f}")
    kws = set(_all_command_keywords(script))
    for cmd in spec.get("required_commands", []):
        if cmd not in kws:
            fails.append(f"missing-command:{cmd}")
    return {"pass": not fails, "fails": fails}


# ---------------- LLM judge (GitHub Models, free tier) ----------------
def _gh_token() -> str:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()


def _parse_verdict(content: str) -> bool | None:
    try:
        start, end = content.index("{"), content.rindex("}") + 1
        obj = json.loads(content[start:end])
        v = obj.get("satisfies_intent")
        if isinstance(v, bool):
            return v
    except Exception:
        pass
    low = content.lower()
    if "true" in low and "false" not in low:
        return True
    if "false" in low and "true" not in low:
        return False
    return None


def judge_once(model: str, intent: str, script: str, token: str) -> bool | None:
    user = f"INTENT:\n{intent}\n\nCANDIDATE SCRIPT:\n```\n{script}\n```"
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 200,
        "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    return _parse_verdict(d["choices"][0]["message"]["content"])


# ---------------- report ----------------
def majority(verdicts: list[bool | None]) -> bool | None:
    v = [x for x in verdicts if x is not None]
    if not v:
        return None
    return sum(v) >= (len(v) + 1) / 2  # tie -> True; we use FAIL-on-tie only at the gate, see writeup


def report(prompts, structural, judged, fixtures_note=""):
    cands = [(p, c) for p in prompts for c in p["candidates"]]
    sb = [(p, c) for p, c in cands if c["kind"] == "structural-bad"]
    sb_caught = [1 for p, c in sb if not structural[c["file"]]["pass"]]
    judged_cands = [(p, c) for p, c in cands if c["kind"] != "structural-bad"]

    print("=== structural scorer (deterministic) ===")
    for p, c in cands:
        s = structural[c["file"]]
        print(f"  {c['file']:34} {'PASS' if s['pass'] else 'FAIL':4}  {';'.join(s['fails'])}")
    print(f"  structural-bad caught by structural: {sum(sb_caught)}/{len(sb)}")
    print(f"  semantic cases left to the judge   : {len([1 for _, c in judged_cands])} "
          f"(structural passes all of them by construction)\n")

    if not judged:
        print("(no judge runs — replay/empty)")
        return
    print("=== judge: accuracy (majority vs gold) + reproducibility (self-agreement) ===")
    print(f"  {fixtures_note}")
    print(f"  {'model':22} {'M':>2} {'accuracy':>9} {'reproducibility':>15}  notes")
    for m in judged:
        mid, M = m["id"], m["M"]
        accs, repros, negctrl_ok = 0, [], 0
        n_neg = 0
        for p, c in judged_cands:
            vs = m["verdicts"][c["file"]]
            maj = majority(vs)
            if maj is not None and bool(maj) == bool(c["gold"]):
                accs += 1
            ok = [x for x in vs if x is not None]
            repros.append((max(ok.count(True), ok.count(False)) / len(ok)) if ok else 0.0)
            if c["kind"] == "semantic-bad":
                n_neg += 1
                if maj is False:
                    negctrl_ok += 1
        n = len(judged_cands)
        acc = accs / n if n else 0
        repro = sum(repros) / len(repros) if repros else 0
        print(f"  {mid:22} {M:>2} {acc:>8.0%} {repro:>14.0%}   neg-control(sem-bad failed): {negctrl_ok}/{n_neg}")


def main() -> None:
    ap = argparse.ArgumentParser(description="V3 eval protocol proof.")
    ap.add_argument("--gmat-root", default=os.environ.get("GMAT_ROOT", ""))
    ap.add_argument("--replay", default=None, help="score from a recorded fixtures file (no model calls)")
    ap.add_argument("--quick", action="store_true", help="M=1 per model (smoke)")
    args = ap.parse_args()

    prompts = json.loads(PROMPTS.read_text())

    # structural is always deterministic / free
    structural = {}
    for p in prompts:
        for c in p["candidates"]:
            text = (CAND_DIR / c["file"]).read_text(encoding="utf-8")
            structural[c["file"]] = structural_score(text, p["structural"])

    if args.replay:
        data = json.loads(Path(args.replay).read_text())
        report(prompts, structural, data["models"], fixtures_note=f"(replayed from {args.replay})")
        return

    token = _gh_token()
    if not token:
        sys.exit("no GH token (set GH_TOKEN or `gh auth login`)")
    judged_cands = [(p, c) for p in prompts for c in p["candidates"] if c["kind"] != "structural-bad"]

    models_out = []
    for spec in MODELS:
        M = 1 if args.quick else spec["M"]
        verdicts = {}
        for p, c in judged_cands:
            script = (CAND_DIR / c["file"]).read_text(encoding="utf-8")
            vs = []
            for _ in range(M):
                try:
                    vs.append(judge_once(spec["id"], p["intent"], script, token))
                except Exception as e:  # noqa: BLE001
                    vs.append(None)
                    sys.stderr.write(f"[{spec['id']}] {c['file']}: {type(e).__name__} {str(e)[:80]}\n")
                time.sleep(PACE_S[spec["tier"]])
            verdicts[c["file"]] = vs
        models_out.append({"id": spec["id"], "M": M, "tier": spec["tier"], "verdicts": verdicts})
        sys.stderr.write(f"done {spec['id']} (M={M})\n")

    FIXTURES.write_text(json.dumps({"models": models_out}, indent=2))
    report(prompts, structural, models_out, fixtures_note=f"(live; fixtures -> {FIXTURES.name})")


if __name__ == "__main__":
    main()
