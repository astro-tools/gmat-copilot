"""The leaderboard Space: the static front end's data contract, and the publish firewall (D16).

The Space renders the committed ``leaderboard.json`` and runs no model. These tests are the contract
between the published board's schema and the static front end that reads it, plus the firewall the
publish step relies on: the board must carry aggregates only, so a held-out gold can never reach the
Space. A browser is not driven here — the *render* is verified by previewing the live Space; what is
locked down is the schema↔front-end agreement and the no-leak property.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from gmat_copilot.eval.leaderboard import LeaderboardError, assert_aggregate_only

REPO_ROOT = Path(__file__).resolve().parents[1]
SPACE_DIR = REPO_ROOT / "leaderboard" / "space"
BOARD_PATH = REPO_ROOT / "leaderboard" / "leaderboard.json"
INDEX_HTML = SPACE_DIR / "index.html"
BOARD_JS = SPACE_DIR / "board.js"
STYLE_CSS = SPACE_DIR / "style.css"
SPACE_README = SPACE_DIR / "README.md"

# The field names the front end reads. The test asserts each appears in board.js *and* exists in the
# committed board, so the schema and the renderer cannot drift apart silently.
TOP_LEVEL_KEYS = (
    "eval_protocol_version",
    "generated_at",
    "judge_model",
    "public_set",
    "held_out_set",
)
ENTRY_KEYS = (
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
)
RUN_KEYS = (
    "tool_version",
    "judge_model",
    "n_votes",
    "recorded_bundle_sha16",
    "verified",
    "submitted_by",
)
CLOSE_THE_LOOP_KEYS = ("repair_lift", "base_runnable", "repaired_runnable", "dry_run_agreement")


@pytest.fixture(scope="module")
def board() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(BOARD_PATH.read_text("utf-8"))
    return data


def test_static_template_files_present() -> None:
    for path in (INDEX_HTML, BOARD_JS, STYLE_CSS, SPACE_README):
        assert path.is_file(), f"missing Space file: {path.name}"
        assert path.read_text("utf-8").strip(), f"empty Space file: {path.name}"


def test_space_readme_declares_static_sdk() -> None:
    text = SPACE_README.read_text("utf-8")
    assert text.startswith("---"), "the HF Space card needs YAML frontmatter"
    front_matter = text.split("---", 2)[1]
    assert "sdk: static" in front_matter, "the Space must be a static SDK Space (decision D16)"
    assert "app_file: index.html" in front_matter


def test_index_html_wires_the_front_end() -> None:
    html = INDEX_HTML.read_text("utf-8")
    assert "board.js" in html and "style.css" in html
    # The mount points board.js writes into must exist in the page.
    for mount in ('id="meta"', 'id="status"', 'id="board"', 'id="rows"'):
        assert mount in html, f"index.html is missing mount {mount}"


def test_board_js_loads_the_board_same_origin() -> None:
    js = BOARD_JS.read_text("utf-8")
    assert "./leaderboard.json" in js, "the Space loads the board published alongside it"


def test_front_end_reads_the_published_schema(board: dict[str, Any]) -> None:
    js = BOARD_JS.read_text("utf-8")
    entry = board["entries"][0]
    for key in (*TOP_LEVEL_KEYS, "entries"):
        assert key in board, f"committed board missing top-level key {key!r}"
        assert key in js, f"front end never reads top-level key {key!r}"
    for key in ENTRY_KEYS:
        assert key in entry, f"committed board entry missing key {key!r}"
        assert key in js, f"front end never reads entry key {key!r}"
    for key in RUN_KEYS:
        assert key in entry["run"], f"committed run block missing key {key!r}"
        assert key in js, f"front end never reads run key {key!r}"
    # close_the_loop may be null on an entry, but the seed row carries it; check any present.
    ctl = next((e["close_the_loop"] for e in board["entries"] if e["close_the_loop"]), None)
    if ctl is not None:
        for key in CLOSE_THE_LOOP_KEYS:
            assert key in ctl, f"committed close_the_loop missing key {key!r}"
            assert key in js, f"front end never reads close_the_loop key {key!r}"


def test_committed_board_is_aggregate_only(board: dict[str, Any]) -> None:
    # The firewall the publish step depends on: the same assertion `leaderboard verify` runs before
    # pushing to the Space. A board that exposes a non-aggregate key must not publish.
    assert_aggregate_only(board)


def test_aggregate_only_rejects_a_leaky_cell() -> None:
    leaky = {
        "entries": [{"model": "x", "public": {"pass_rate": 1.0, "request": "leak"}, "held_out": {}}]
    }
    with pytest.raises(LeaderboardError):
        assert_aggregate_only(leaky)


def test_published_board_carries_no_prompt_text(board: dict[str, Any]) -> None:
    # No prompt/intent/verdict key anywhere in a row — a stronger, structural no-leak check than the
    # aggregate-key allowlist (a held-out gold would arrive under one of these names).
    forbidden = {"request", "intent", "prompts", "completions", "judge", "verdict", "verdicts"}
    for entry in board["entries"]:
        assert not (set(entry) & forbidden)
        for cell in ("public", "held_out"):
            assert not (set(entry[cell]) & forbidden)


def test_injected_board_copy_is_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text("utf-8")
    assert "leaderboard/space/leaderboard.json" in gitignore


def _load_author_heldout() -> Any:
    spec = importlib.util.spec_from_file_location(
        "author_heldout", REPO_ROOT / "leaderboard" / "tools" / "author_heldout.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_author_heldout_scaffolds_placeholders_only() -> None:
    module = _load_author_heldout()
    reference = json.loads((REPO_ROOT / "tests/data/eval/prompts.json").read_text("utf-8"))
    prompts = module.scaffold(5, reference)
    assert len(prompts) == 5
    for prompt in prompts:
        # The schema mirrors the public set; the content is a placeholder, never a real gold.
        assert set(prompt) == {"id", "difficulty", "request", "intent", "structural"}
        assert "TODO-HELDOUT" in prompt["request"] and "TODO-HELDOUT" in prompt["intent"]
        assert "required_types" in prompt["structural"]
