"""The per-model leaderboard engine (decision D16): ranking, the firewall, and reproducibility.

Every number comes from the *shipped* recorded scorer (``run_recorded`` / ``run_recorded_lift``) —
the same code the board runs in gated CI, never a mock. The committed public bundle anchors the
frozen numbers; a synthetic, never-committed held-out (built in ``tmp_path``, outside the repo tree)
drives the held-out-headline ranking and the leak checks, since the held-out is private by design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gmat_copilot.eval.leaderboard import (
    Aggregate,
    BoardRow,
    LeaderboardError,
    RunMeta,
    assert_aggregate_only,
    assert_no_leak,
    build_from_config,
    build_leaderboard,
    close_the_loop_from_lift,
    dumps,
    held_out_secrets,
    recorded_usage,
    score_entry,
    summarize,
)
from gmat_copilot.eval.lift import DraftScore, LiftReport, LiftRow
from gmat_copilot.eval.runner import run_recorded
from gmat_copilot.eval.scorer import StructuralResult
from gmat_copilot.providers import prompt_key

MODEL = "openai/gpt-4.1-mini"
REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_VERSION = "0.0.0-test"  # injected, never read from the package, so the board is byte-stable

# A clean script that satisfies SPEC below; the `DryMas` typo raises one `unknown-field` WARNING the
# structural gate blocks on (decision D5) — so emitting GOOD passes a prompt and BAD fails it.
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
BAD_SCRIPT = GOOD_SCRIPT.replace("Sat.TA = 0;", "Sat.TA = 0;\nSat.DryMas = 850;")

SPEC = {
    "required_types": ["Spacecraft", "Propagator", "ReportFile"],
    "required_fields": {"Spacecraft": ["SMA", "ECC", "INC"]},
    "required_commands": ["Propagate", "Report"],
}

# Baked into every held-out request/intent so the leak check can assert it never reaches the board.
HELDOUT_SENTINEL = "HELDOUT-PRIVATE-DO-NOT-PUBLISH"


def _prompt(pid: str, *, secret: bool) -> dict[str, Any]:
    """A bundle prompt; held-out prompts (``secret=True``) carry the sentinel in their gold text."""
    mark = f"{HELDOUT_SENTINEL}: " if secret else ""
    return {
        "id": pid,
        "difficulty": "easy",
        "request": f"{mark}author mission {pid}.",
        "intent": f"{mark}the gold intent for {pid}.",
        "structural": SPEC,
    }


def _write_bundle(
    bundle_dir: Path, prompts: list[dict[str, Any]], emissions: dict[str, dict[str, str]]
) -> None:
    """Write a recorded static bundle: prompts + per-model completions + all-True gold verdicts.

    The gold verdict is a fixed ``True`` per prompt, so the *structural* layer is the sole
    discriminator — the model-specific script (GOOD vs BAD) decides the pass.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    by_id = {p["id"]: p for p in prompts}
    completions: dict[str, dict[str, Any]] = {}
    for model, scripts in emissions.items():
        for pid, script in scripts.items():
            key = prompt_key("github", model, by_id[pid]["request"])
            completions[key] = {"text": script, "usage": {}}
    (bundle_dir / "prompts.json").write_text(json.dumps(prompts, indent=2), "utf-8")
    (bundle_dir / "completions.json").write_text(json.dumps(completions, indent=2), "utf-8")
    (bundle_dir / "judge.json").write_text(
        json.dumps({p["id"]: [True] for p in prompts}, indent=2), "utf-8"
    )


# --- the committed public anchor reproduces the frozen numbers (decisions D6, D7) ---


@pytest.mark.eval_smoke
def test_score_entry_reproduces_the_frozen_public_anchor(
    eval_bundle: Path, eval_lift_bundle: Path
) -> None:
    row = score_entry(
        MODEL,
        public_bundle=eval_bundle,
        lift_bundle=eval_lift_bundle,
        tool_version=TOOL_VERSION,
        provider="github",
    )
    assert row.public == Aggregate(
        pass_rate=0.804, by_tier={"easy": 0.85, "hard": 0.846, "medium": 0.722}, n_prompts=51
    )
    assert row.held_out is None and row.overfit_gap is None  # held-out is gated-CI only
    assert row.close_the_loop is not None
    assert row.close_the_loop.repair_lift == 0.5
    assert row.close_the_loop.base_runnable == 0.25
    assert row.close_the_loop.repaired_runnable == 0.75
    assert row.run.recorded_bundle_sha16 == "a0cab7b3f7de44b4"
    assert row.usage["generation_calls"] == 51 and row.usage["judge_calls"] == 153


@pytest.mark.eval_smoke
def test_board_is_byte_deterministic(eval_bundle: Path) -> None:
    def build() -> str:
        row = score_entry(MODEL, public_bundle=eval_bundle, tool_version=TOOL_VERSION)
        board = build_leaderboard(
            [row],
            eval_protocol_version="1",
            generated_at="2026-01-01T00:00:00Z",
            judge_model=MODEL,
            public_set={"committed": True},
            held_out_set={"committed": False},
        )
        return dumps(board)

    assert build() == build()  # injected generated_at + sorted keys ⇒ byte-identical


# --- the held-out is the headline: overfitting the public buys no rank (decision D16) ---


def _board_with_heldout(tmp_path: Path) -> dict[str, Any]:
    """Build a two-model board over a synthetic public mirror + a never-committed held-out."""
    public_prompts = [_prompt("pub_a", secret=False), _prompt("pub_b", secret=False)]
    held_out_prompts = [_prompt("ho_a", secret=True), _prompt("ho_b", secret=True)]
    # `honest` is weaker on the public mirror but generalises; `overfit` aces public, fails held.
    public_emit = {
        "demo/honest": {"pub_a": GOOD_SCRIPT, "pub_b": BAD_SCRIPT},
        "demo/overfit": {"pub_a": GOOD_SCRIPT, "pub_b": GOOD_SCRIPT},
    }
    held_out_emit = {
        "demo/honest": {"ho_a": GOOD_SCRIPT, "ho_b": GOOD_SCRIPT},
        "demo/overfit": {"ho_a": BAD_SCRIPT, "ho_b": BAD_SCRIPT},
    }
    public_dir = tmp_path / "public_mirror"
    held_out_dir = tmp_path / "private_heldout"  # NEVER under the repo tree
    _write_bundle(public_dir, public_prompts, public_emit)
    _write_bundle(held_out_dir, held_out_prompts, held_out_emit)
    assert not str(held_out_dir.resolve()).startswith(str(REPO_ROOT))

    rows = [
        score_entry(
            model,
            public_bundle=public_dir,
            held_out_bundle=held_out_dir,
            tool_version=TOOL_VERSION,
            provider="recorded",
            kind="illustrative",
        )
        for model in ("demo/honest", "demo/overfit")
    ]
    return build_leaderboard(
        rows,
        eval_protocol_version="1",
        generated_at="2026-01-01T00:00:00Z",
        judge_model=MODEL,
        public_set={"committed": True},
        held_out_set={"committed": False, "sentinel": "n/a"},
    )


def test_held_out_headline_ranks_the_honest_model_first(tmp_path: Path) -> None:
    board = _board_with_heldout(tmp_path)
    by_model = {row["model"]: row for row in board["entries"]}
    honest, overfit = by_model["demo/honest"], by_model["demo/overfit"]

    # The overfit model tops the PUBLIC column ...
    assert overfit["public"]["pass_rate"] > honest["public"]["pass_rate"]
    # ... yet the board ranks on the HELD-OUT headline, so the honest model wins rank 1.
    assert honest["held_out"]["pass_rate"] > overfit["held_out"]["pass_rate"]
    assert honest["rank"] == 1 and overfit["rank"] == 2


def test_overfit_gap_is_the_tell(tmp_path: Path) -> None:
    board = _board_with_heldout(tmp_path)
    by_model = {row["model"]: row for row in board["entries"]}
    assert by_model["demo/overfit"]["overfit_gap"] > 0  # public ≫ held-out
    assert by_model["demo/honest"]["overfit_gap"] < 0


# --- the firewall: the published board leaks no held-out gold (decision D16) ---


def test_board_carries_no_held_out_gold(tmp_path: Path) -> None:
    board = _board_with_heldout(tmp_path)
    serialized = dumps(board)
    assert HELDOUT_SENTINEL not in serialized  # the held-out requests/intents never reach the board
    assert_no_leak(serialized, [HELDOUT_SENTINEL])
    assert_aggregate_only(board)  # cells expose only pass-rate aggregates


def test_assert_aggregate_only_rejects_a_leaked_cell() -> None:
    leaky = {
        "entries": [
            {"model": "demo/x", "public": {"pass_rate": 1.0}, "held_out": {"intent": "secret gold"}}
        ]
    }
    with pytest.raises(LeaderboardError, match="aggregate-only"):
        assert_aggregate_only(leaky)


def test_assert_no_leak_raises_when_a_secret_appears() -> None:
    with pytest.raises(LeaderboardError, match="leaked"):
        assert_no_leak(
            '{"held_out": {"status": "HELDOUT-PRIVATE-DO-NOT-PUBLISH"}}', [HELDOUT_SENTINEL]
        )


def test_held_out_secrets_reads_the_private_request_and_intent_text(tmp_path: Path) -> None:
    held_out_root = tmp_path / "heldout"
    _write_bundle(
        held_out_root / "demo__m", [_prompt("h", secret=True)], {"demo/m": {"h": GOOD_SCRIPT}}
    )
    config = {"seeds": [{"model": "demo/m", "held_out_bundle": "demo__m"}]}
    secrets = held_out_secrets(config, held_out_root)
    assert len(secrets) == 2 and all(HELDOUT_SENTINEL in s for s in secrets)  # request + intent
    # a seed whose held-out bundle has not been fetched contributes nothing (a no-op offline)
    absent = {"seeds": [{"model": "x", "held_out_bundle": "absent"}]}
    assert held_out_secrets(absent, held_out_root) == []


def test_build_runs_the_content_firewall_over_held_out_secrets(tmp_path: Path) -> None:
    # The board is aggregate-only, so to prove the *content* scan runs we contrive a held-out gold
    # equal to a published model name — which legitimately appears in the board — and assert the
    # gated build fails rather than publishing it.
    public_dir = tmp_path / "public"
    held_out_root = tmp_path / "heldout"
    _write_bundle(public_dir, [_prompt("p", secret=False)], {"demo/m": {"p": GOOD_SCRIPT}})
    leak = {
        "id": "h",
        "difficulty": "easy",
        "request": "demo/m",
        "intent": "demo/m",
        "structural": SPEC,
    }
    _write_bundle(held_out_root / "demo__m", [leak], {"demo/m": {"h": GOOD_SCRIPT}})
    config = {
        "seeds": [
            {
                "provider": "github",
                "model": "demo/m",
                "public_bundle": "public",
                "held_out_bundle": "demo__m",
            }
        ]
    }
    with pytest.raises(LeaderboardError, match="leaked"):
        build_from_config(
            config,
            root=tmp_path,
            generated_at="2026-01-01T00:00:00Z",
            tool_version=TOOL_VERSION,
            held_out_root=held_out_root,
        )


def test_recorded_usage_coerces_float_token_totals(tmp_path: Path) -> None:
    # Token counts recorded as floats (e.g. 1234.0) are summed, not silently dropped; a bool is not.
    bundle = tmp_path / "b"
    _write_bundle(bundle, [_prompt("p", secret=False)], {"demo/m": {"p": GOOD_SCRIPT}})
    comp_path = bundle / "completions.json"
    comp = json.loads(comp_path.read_text("utf-8"))
    key = next(iter(comp))
    comp[key]["usage"] = {"total_tokens": 1234.0, "prompt_tokens": 1000, "flag": True}
    comp_path.write_text(json.dumps(comp), "utf-8")
    usage = recorded_usage(bundle, model="demo/m", n_votes=3)
    assert usage["total_tokens"] == 1234  # float coerced to int, not dropped
    assert usage["prompt_tokens"] == 1000
    assert "flag" not in usage  # a bool usage field is excluded, not summed as 1


# --- pending held-out and ranking edge cases ---


def test_pending_held_out_is_marked_and_sorts_last(eval_bundle: Path, tmp_path: Path) -> None:
    bundle = _one_prompt_bundle(tmp_path)
    scored = score_entry(
        "demo/scored", public_bundle=bundle, held_out_bundle=bundle, tool_version=TOOL_VERSION
    )
    pending = score_entry(
        MODEL, public_bundle=eval_bundle, tool_version=TOOL_VERSION
    )  # no held-out
    board = build_leaderboard(
        [pending, scored],
        eval_protocol_version="1",
        generated_at="2026-01-01T00:00:00Z",
        judge_model=MODEL,
        public_set={},
        held_out_set={},
    )
    ranks = {row["model"]: row["rank"] for row in board["entries"]}
    assert (
        ranks["demo/scored"] == 1 and ranks[MODEL] == 2
    )  # the scored held-out outranks the pending
    pending_cell = next(r for r in board["entries"] if r["model"] == MODEL)["held_out"]
    assert pending_cell["pass_rate"] is None and "pending" in pending_cell["status"]


def _one_prompt_bundle(tmp_path: Path) -> Path:
    """A trivial single-prompt bundle whose one model passes (so its pass-rate is 1.0)."""
    bundle = tmp_path / "scored"
    _write_bundle(bundle, [_prompt("only", secret=False)], {"demo/scored": {"only": GOOD_SCRIPT}})
    return bundle


def test_pending_row_is_built_with_held_out_bundle(tmp_path: Path) -> None:
    bundle = _one_prompt_bundle(tmp_path)
    row = score_entry(
        "demo/scored", public_bundle=bundle, held_out_bundle=bundle, tool_version=TOOL_VERSION
    )
    assert row.held_out == Aggregate(pass_rate=1.0, by_tier={"easy": 1.0}, n_prompts=1)
    assert row.overfit_gap == 0.0


# --- the committed seed config + board stay valid and reproducible (decisions D7, D16) ---


def test_committed_config_builds_the_seed_public_row() -> None:
    config = json.loads((REPO_ROOT / "leaderboard" / "seeds.json").read_text("utf-8"))
    board, notes = build_from_config(
        config, root=REPO_ROOT, generated_at="2026-01-01T00:00:00Z", tool_version=TOOL_VERSION
    )
    models = [row["model"] for row in board["entries"]]
    assert (
        MODEL in models
    )  # the gpt-4.1-mini public row is offline-reproducible from the committed bundle
    # the second seed has no committed public bundle offline → skipped with a note, not an error
    assert any("gpt-4o-mini" in note for note in notes)
    seed_row = next(row for row in board["entries"] if row["model"] == MODEL)
    assert seed_row["public"]["pass_rate"] == 0.804
    assert seed_row["held_out"]["pass_rate"] is None  # no held-out committed (the firewall)
    assert_aggregate_only(board)


def test_committed_board_public_row_reproduces() -> None:
    board = json.loads((REPO_ROOT / "leaderboard" / "leaderboard.json").read_text("utf-8"))
    assert_aggregate_only(board)
    row = next(r for r in board["entries"] if r["model"] == MODEL)
    got = summarize(run_recorded(REPO_ROOT / "tests" / "data" / "eval", model=MODEL)).to_dict()
    assert got == row["public"]  # the published public number reproduces from the bundle


def test_build_from_config_skips_seeds_with_no_public_bundle() -> None:
    config = {
        "seeds": [{"provider": "github", "model": "demo/absent", "public_bundle": "nope/missing"}]
    }
    board, notes = build_from_config(
        config, root=REPO_ROOT, generated_at="2026-01-01T00:00:00Z", tool_version=TOOL_VERSION
    )
    assert board["entries"] == [] and any("demo/absent" in note for note in notes)


# --- the gated-CI config paths: held-out scoring + a model absent from its bundle ---


def test_build_from_config_scores_the_held_out_when_present(tmp_path: Path) -> None:
    """The gated-CI path: with held_out_root set and the bundle present, the held-out scores."""
    public_dir = tmp_path / "public"
    held_out_dir = tmp_path / "heldout" / "demo__m"  # resolved under held_out_root, never committed
    _write_bundle(public_dir, [_prompt("p", secret=False)], {"demo/m": {"p": GOOD_SCRIPT}})
    _write_bundle(held_out_dir, [_prompt("h", secret=True)], {"demo/m": {"h": BAD_SCRIPT}})
    # a second model whose held-out has NOT been fetched → held-out stays pending, exercising the
    # held-out-absent arc even though held_out_root is set.
    other_public = tmp_path / "other"
    _write_bundle(other_public, [_prompt("p", secret=False)], {"demo/n": {"p": GOOD_SCRIPT}})
    config = {
        "seeds": [
            {
                "provider": "github",
                "model": "demo/m",
                "public_bundle": "public",
                "held_out_bundle": "demo__m",
            },
            {
                "provider": "github",
                "model": "demo/n",
                "public_bundle": "other",
                "held_out_bundle": "demo__n",  # no such bundle under held_out_root → pending
            },
        ]
    }
    board, notes = build_from_config(
        config,
        root=tmp_path,
        generated_at="2026-01-01T00:00:00Z",
        tool_version=TOOL_VERSION,
        held_out_root=tmp_path / "heldout",
    )
    scored = next(r for r in board["entries"] if r["model"] == "demo/m")
    pending = next(r for r in board["entries"] if r["model"] == "demo/n")
    assert scored["public"]["pass_rate"] == 1.0  # GOOD passes
    assert scored["held_out"]["pass_rate"] == 0.0  # BAD fails the structural gate
    assert scored["overfit_gap"] == 1.0
    assert pending["held_out"]["pass_rate"] is None  # held-out bundle absent → pending
    assert notes == []


def test_build_from_config_skips_a_model_missing_from_its_bundle(tmp_path: Path) -> None:
    """A present bundle that lacks the seed's model → ProviderError → skipped with a note."""
    public_dir = tmp_path / "public"
    _write_bundle(public_dir, [_prompt("p", secret=False)], {"other/model": {"p": GOOD_SCRIPT}})
    config = {"seeds": [{"provider": "github", "model": "demo/wanted", "public_bundle": "public"}]}
    board, notes = build_from_config(
        config, root=tmp_path, generated_at="2026-01-01T00:00:00Z", tool_version=TOOL_VERSION
    )
    assert board["entries"] == [] and any("demo/wanted" in note for note in notes)


def test_close_the_loop_marks_an_undefined_dry_run_agreement_tier() -> None:
    """A tier with no statically-accepted base draft has an undefined (``None``) agreement (D12)."""
    failing = DraftScore(
        structural=StructuralResult(passed=False, failures=("x",)), judge=False, dry_run_ok=None
    )
    row = LiftRow(
        id="r", difficulty="easy", base=failing, repaired=failing, retries=0, stop_reason="budget"
    )
    cell = close_the_loop_from_lift(LiftReport(rows=(row,)))
    assert cell.dry_run_agreement == {"easy": None}


# --- RunMeta / BoardRow round-trip the documented schema keys ---


def test_row_to_dict_carries_the_documented_schema() -> None:
    row = BoardRow(
        provider="github",
        model="demo/x",
        kind="seed",
        public=Aggregate(pass_rate=0.5, by_tier={"easy": 0.5}, n_prompts=2),
        held_out=Aggregate(pass_rate=0.4, by_tier={"easy": 0.4}, n_prompts=2),
        close_the_loop=None,
        usage={"generation_calls": 2, "judge_calls": 6},
        run=RunMeta(
            tool_version=TOOL_VERSION,
            judge_model=MODEL,
            n_votes=3,
            recorded_bundle_sha16="deadbeefdeadbeef",
            verified=True,
            submitted_by="seed",
        ),
    )
    out = row.to_dict(rank=1)
    assert set(out) == {
        "rank",
        "provider",
        "model",
        "kind",
        "public",
        "held_out",
        "overfit_gap",
        "close_the_loop",
        "usage",
        "run",
    }
    assert out["overfit_gap"] == pytest.approx(0.1)
