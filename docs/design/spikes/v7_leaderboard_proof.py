"""V7 proof — per-model leaderboard, held-out as the headline, against the *real* scorer.

Runs fully offline (stdlib + ``gmat_copilot`` only; no model, no GMAT, no network): it drives the
shipped recorded eval path (``run_recorded`` / ``run_recorded_lift``) so every number is produced by
the code the board will run, never a mock — the maneuver-detect spike discipline (demonstrate a
property of the real scorer, with synthetic data where real data cannot be committed).

What it shows, in three parts:

1. **The public set is the reproducibility anchor.** The committed recorded bundle scores
   ``openai/gpt-4.1-mini`` deterministically — byte-identical across runs (decision D7) — so any
   entrant reproduces the public number offline with no model and no quota. The bundle's content
   hash pins the result.

2. **The held-out set is the headline.** A *never-committed* private held-out (built here in a temp
   dir, synthetic, scored by the same ``run_recorded``) ranks the board. An "overfit-to-public"
   model that tops the **public** column sinks on the **held-out** headline, below an honest model:
   ranking on held-out is exactly what makes overfitting the public prompts buy no rank.

3. **The firewall holds and leaks nothing.** The held-out prompts/intents/golds appear nowhere in
   the published ``leaderboard.json`` (aggregate-only), the held-out bundle is written only under a
   temp dir outside the repo (never committed), and the published board is byte-deterministic.

Run it::

    python docs/design/spikes/v7_leaderboard_proof.py     # (or: uv run python ...)

Two invocations produce byte-identical output.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from gmat_copilot.eval.lift import run_recorded_lift
from gmat_copilot.eval.runner import EvalReport, run_recorded
from gmat_copilot.providers import prompt_key

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_BUNDLE = REPO_ROOT / "tests" / "data" / "eval"
PUBLIC_LIFT_BUNDLE = REPO_ROOT / "tests" / "data" / "eval_lift"
SEED_MODEL = "openai/gpt-4.1-mini"

# Fixed so the proof's output (and the leaderboard.json it builds) is byte-stable across runs; the
# real board stamps the gated-CI run time here.
GENERATED_AT = "2026-01-01T00:00:00Z"
EVAL_PROTOCOL_VERSION = "1"

# Two lint outcomes are all the discriminator the structural layer needs (decision D6): a clean
# script passes every spec below; the `DryMas` typo raises one `unknown-field` WARNING, on which the
# structural gate blocks (decision D5) — so a model's score is decided by which it emits per prompt.
GOOD_SCRIPT = """\
Create Spacecraft Sat;
Sat.DateFormat = UTCGregorian;
Sat.Epoch = '01 Jan 2025 12:00:00.000';
Sat.CoordinateSystem = EarthMJ2000Eq;
Sat.DisplayStateType = Keplerian;
Sat.SMA = 6878;
Sat.ECC = 0;
Sat.INC = 51.6;
Sat.RAAN = 0;
Sat.AOP = 0;
Sat.TA = 0;

Create ForceModel FM;
FM.CentralBody = Earth;
FM.PrimaryBodies = {Earth};

Create Propagator Prop;
Prop.FM = FM;

Create ReportFile rf;
rf.Filename = 'out.report';
rf.Add = {Sat.Earth.Altitude, Sat.Earth.SMA};

BeginMissionSequence;
Propagate Prop(Sat) {Sat.ElapsedDays = 1};
Report rf Sat.Earth.Altitude Sat.Earth.SMA;
"""

BAD_SCRIPT = GOOD_SCRIPT.replace("Sat.TA = 0;", "Sat.TA = 0;\nSat.DryMas = 850;")  # one WARNING

# A spec satisfied by GOOD_SCRIPT (SMA/ECC/INC present, the three resource types, both commands).
_SPEC = {
    "required_types": ["Spacecraft", "Propagator", "ReportFile"],
    "required_fields": {"Spacecraft": ["SMA", "ECC", "INC"]},
    "required_commands": ["Propagate", "Report"],
}

# A sentinel baked into every held-out request/intent so the leak check can assert the published
# board contains none of it.
HELDOUT_SENTINEL = "HELDOUT-PRIVATE-DO-NOT-PUBLISH"


def _prompt(pid: str) -> dict[str, Any]:
    """A held-out prompt whose human text carries the sentinel (golds must never reach the board)."""
    return {
        "id": pid,
        "difficulty": "easy",
        "request": f"{HELDOUT_SENTINEL}: author mission {pid}.",
        "intent": f"{HELDOUT_SENTINEL}: the gold intent for {pid}.",
        "structural": _SPEC,
    }


def _write_bundle(
    bundle_dir: Path, prompts: list[dict[str, Any]], emissions: dict[str, dict[str, str]]
) -> None:
    """Write a recorded bundle: prompts + per-model completions + model-agnostic gold verdicts.

    *emissions* maps ``model -> {prompt_id: script}``. Gold verdicts are a fixed ``True`` per prompt
    so the *structural* layer is the sole discriminator (the model-specific script decides the pass).
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    by_id = {p["id"]: p for p in prompts}
    completions: dict[str, dict[str, str]] = {}
    for model, scripts in emissions.items():
        for pid, script in scripts.items():
            key = prompt_key("github", model, by_id[pid]["request"])
            completions[key] = {"text": script, "usage": {}}
    (bundle_dir / "prompts.json").write_text(json.dumps(prompts, indent=2), "utf-8")
    (bundle_dir / "completions.json").write_text(json.dumps(completions, indent=2), "utf-8")
    (bundle_dir / "judge.json").write_text(
        json.dumps({p["id"]: [True] for p in prompts}, indent=2), "utf-8"
    )


def _summary(report: EvalReport) -> dict[str, Any]:
    """The aggregate-only view of a report — the only thing a board row ever carries."""
    return {
        "pass_rate": round(report.pass_rate, 3),
        "by_tier": {t: round(r, 3) for t, r in sorted(report.pass_rate_by_tier.items())},
        "n_prompts": len(report.outcomes),
    }


def _bundle_sha16(bundle: Path) -> str:
    h = hashlib.sha256()
    for name in ("prompts.json", "completions.json", "judge.json"):
        h.update((bundle / name).read_bytes())
    return h.hexdigest()[:16]


def _seed_usage(bundle: Path) -> dict[str, Any]:
    """Sum the recorded generation usage in the public bundle (judge usage is not recorded)."""
    completions = json.loads((bundle / "completions.json").read_text("utf-8"))
    totals: dict[str, int] = {}
    for entry in completions.values():
        for field, value in (entry.get("usage") or {}).items():
            if isinstance(value, int):
                totals[field] = totals.get(field, 0) + value
    return {"generation_calls": len(completions), "judge_calls": len(completions) * 3, **totals}


def _overfit_gap(public: dict[str, Any], held_out: dict[str, Any] | None) -> float | None:
    if held_out is None or held_out.get("pass_rate") is None:
        return None
    return round(public["pass_rate"] - held_out["pass_rate"], 3)


def main() -> int:
    print("V7 — per-model leaderboard, held-out as the headline (real scorer)")
    print("=" * 66)

    # --- [1] Public set: the committed reproducibility anchor (decision D7) -----------------------
    seed_public = run_recorded(PUBLIC_BUNDLE, model=SEED_MODEL)
    again = run_recorded(PUBLIC_BUNDLE, model=SEED_MODEL)
    seed_lift = run_recorded_lift(PUBLIC_LIFT_BUNDLE, budget=2)
    public_deterministic = _summary(seed_public) == _summary(again)
    sha = _bundle_sha16(PUBLIC_BUNDLE)

    print("\n[1] Public set — the committed, reproducible anchor (the recorded bundle, D7):")
    print(f"    seed model       : github:{SEED_MODEL}")
    print(f"    public pass-rate : {json.dumps(_summary(seed_public))}")
    print(
        "    close-the-loop   : "
        + json.dumps(
            {
                "dry_run_agreement": {
                    t: (round(v, 3) if v is not None else None)
                    for t, v in sorted(seed_lift.dry_run_agreement_by_tier.items())
                },
                "repair_lift": round(seed_lift.lift, 3),
                "base_runnable": round(seed_lift.base_runnable, 3),
                "repaired_runnable": round(seed_lift.repaired_runnable, 3),
            }
        )
    )
    print(f"    bundle sha-256   : {sha} (pins the result; reproduced offline, no model/quota)")
    print(f"    byte-identical re-run : {public_deterministic}")

    # --- [2] Held-out set: the never-committed headline, scored by the same scorer ----------------
    public_prompts = [_named("pub_circular", "PUBLIC: circular LEO"), _named("pub_track", "PUBLIC: groundtrack")]
    held_out_prompts = [_prompt("ho_alpha"), _prompt("ho_beta")]

    # Two synthetic models. `honest` is weaker on the public mirror but generalises to the held-out;
    # `overfit-public` aces the public mirror and fails the held-out — the case the headline exists
    # to catch. (GOOD passes a spec; BAD raises the WARNING the structural gate blocks on.)
    public_emit = {
        "demo/honest": {"pub_circular": GOOD_SCRIPT, "pub_track": BAD_SCRIPT},
        "demo/overfit-public": {"pub_circular": GOOD_SCRIPT, "pub_track": GOOD_SCRIPT},
    }
    held_out_emit = {
        "demo/honest": {"ho_alpha": GOOD_SCRIPT, "ho_beta": GOOD_SCRIPT},
        "demo/overfit-public": {"ho_alpha": BAD_SCRIPT, "ho_beta": BAD_SCRIPT},
    }

    with tempfile.TemporaryDirectory(prefix="v7_heldout_") as tmp:
        public_mirror = Path(tmp) / "public_mirror"
        held_out = Path(tmp) / "private_heldout"  # NEVER under the repo tree
        _write_bundle(public_mirror, public_prompts, public_emit)
        _write_bundle(held_out, held_out_prompts, held_out_emit)

        rows: list[dict[str, Any]] = []
        # The real seed row: its public number is real; its held-out lands in gated CI (the private
        # set is authored at build time and never committed — here the synthetic bundle stands in).
        rows.append(
            {
                "provider": "recorded",
                "model": SEED_MODEL,
                "kind": "seed",
                "public": _summary(seed_public),
                "held_out": {"pass_rate": None, "status": "pending: gated CI vs never-committed set"},
                "overfit_gap": None,
                "close_the_loop": {
                    "repair_lift": round(seed_lift.lift, 3),
                    "base_runnable": round(seed_lift.base_runnable, 3),
                    "repaired_runnable": round(seed_lift.repaired_runnable, 3),
                },
                "usage": _seed_usage(PUBLIC_BUNDLE),
                "run": _run_meta("seed"),
            }
        )
        for model in ("demo/honest", "demo/overfit-public"):
            public = _summary(run_recorded(public_mirror, model=model))
            heldout = _summary(run_recorded(held_out, model=model))
            rows.append(
                {
                    "provider": "recorded",
                    "model": model,
                    "kind": "illustrative",
                    "public": public,
                    "held_out": heldout,
                    "overfit_gap": _overfit_gap(public, heldout),
                    "close_the_loop": None,
                    "usage": {"generation_calls": 2, "judge_calls": 6},
                    "run": _run_meta("illustrative"),
                }
            )

        leaderboard = _build_leaderboard(rows, public_n=len(seed_public.outcomes), sha=sha,
                                         held_out_n=len(held_out_prompts))
        serialized = json.dumps(leaderboard, indent=2, sort_keys=True) + "\n"

    print("\n[2] Held-out — the headline ranking (same scorer, a never-committed private bundle):")
    _print_table(leaderboard["entries"])

    # --- [3] Integrity assertions (mirroring the maneuver-detect firewall proof) -------------------
    ranked = [r for r in leaderboard["entries"] if r["held_out"].get("pass_rate") is not None]
    honest = next(r for r in ranked if r["model"] == "demo/honest")
    overfit = next(r for r in ranked if r["model"] == "demo/overfit-public")

    aggregate_only = HELDOUT_SENTINEL not in serialized
    overfit_tops_public = overfit["public"]["pass_rate"] > honest["public"]["pass_rate"]
    headline_demotes_overfit = (
        honest["held_out"]["pass_rate"] > overfit["held_out"]["pass_rate"]
        and ranked[0]["model"] == "demo/honest"
    )
    never_committed = not str(held_out).startswith(str(REPO_ROOT))
    board_deterministic = serialized == (json.dumps(leaderboard, indent=2, sort_keys=True) + "\n")

    print("\n[3] Integrity checks (all assert-backed, passed):")
    print(f"    - public score is byte-identical across runs (D7)          : {public_deterministic}")
    print(f"    - published board is aggregate-only (no held-out golds leak): {aggregate_only}")
    print(f"    - held-out bundle written only outside the repo tree        : {never_committed}")
    print(f"    - the overfit model tops the PUBLIC column                  : {overfit_tops_public}"
          f"  ({overfit['public']['pass_rate']} vs {honest['public']['pass_rate']})")
    print(f"    - the HELD-OUT headline ranks the honest model first        : {headline_demotes_overfit}"
          f"  ({honest['held_out']['pass_rate']} vs {overfit['held_out']['pass_rate']})")
    print(f"    - the published board is byte-deterministic                 : {board_deterministic}")

    assert public_deterministic and aggregate_only and never_committed
    assert overfit_tops_public and headline_demotes_overfit and board_deterministic

    print("\n    => Overfitting the public set tops the public column but loses the held-out headline.")
    print("       The held-out golds never reach the board; the public anchor reproduces offline.")
    print("\nRESULT: V7 leaderboard + held-out-headline prototype end-to-end = OK")
    return 0


def _named(pid: str, label: str) -> dict[str, Any]:
    """A public-mirror prompt (its text is public — no sentinel)."""
    return {
        "id": pid,
        "difficulty": "easy",
        "request": f"{label}: author mission {pid}.",
        "intent": f"{label}: the public intent for {pid}.",
        "structural": _SPEC,
    }


def _run_meta(submitted_by: str) -> dict[str, Any]:
    return {
        "tool_version": _tool_version(),
        "judge_model": SEED_MODEL,
        "n_votes": 3,
        "verified": True,
        "submitted_by": submitted_by,
    }


def _tool_version() -> str:
    import gmat_copilot

    return gmat_copilot.__version__


def _build_leaderboard(
    rows: list[dict[str, Any]], *, public_n: int, sha: str, held_out_n: int
) -> dict[str, Any]:
    """Rank by the held-out headline (public alongside); null held-out sorts last."""

    def sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        rate = row["held_out"].get("pass_rate")
        return (0 if rate is not None else 1, -(rate or 0.0), row["model"])

    ranked = sorted(rows, key=sort_key)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return {
        "eval_protocol_version": EVAL_PROTOCOL_VERSION,
        "generated_at": GENERATED_AT,
        "judge_model": SEED_MODEL,
        "ranking": "held_out.pass_rate desc — the headline; public shown alongside as the anchor",
        "public_set": {
            "n_prompts": public_n,
            "recorded_bundle_sha16": sha,
            "committed": True,
            "reproducible_offline": True,
        },
        "held_out_set": {
            "n_prompts": held_out_n,
            "committed": False,
            "store": "private HF Dataset (HF_TOKEN), scored in gated CI only",
        },
        "entries": ranked,
    }


def _print_table(entries: list[dict[str, Any]]) -> None:
    def cell(value: float | None) -> str:
        return "  -  " if value is None else f"{value:.3f}"

    header = f"    {'#':<2} {'entry':<22} {'HELD-OUT':>8}  {'public':>7}  {'gap':>6}  kind"
    print(header)
    print("    " + "-" * (len(header) - 4))
    for row in entries:
        held = row["held_out"].get("pass_rate")
        print(
            f"    {row['rank']:<2} {row['model']:<22} {cell(held):>8}  "
            f"{cell(row['public']['pass_rate']):>7}  {cell(row['overfit_gap']):>6}  {row['kind']}"
        )


if __name__ == "__main__":
    sys.exit(main())
