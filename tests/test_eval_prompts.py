"""The eval prompt set: the loader's defaults and the shipped ~50-prompt suite (decision D6)."""

from __future__ import annotations

import collections
import json
from pathlib import Path

from gmat_copilot.eval import load_prompts

SUITE = Path(__file__).parent / "data" / "eval" / "prompts.json"


def test_load_prompts_applies_defaults(tmp_path: Path) -> None:
    # A minimal entry: no difficulty (defaults to easy) and no structural (defaults to empty).
    path = tmp_path / "p.json"
    path.write_text(json.dumps([{"id": "x", "request": "r", "intent": "i"}]), encoding="utf-8")
    (prompt,) = load_prompts(path)
    assert prompt.difficulty == "easy"
    assert prompt.structural.required_types == ()
    assert prompt.structural.required_fields == {}
    assert prompt.structural.required_commands == ()


def test_load_prompts_reads_the_full_spec(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "x",
                    "difficulty": "hard",
                    "request": "r",
                    "intent": "i",
                    "structural": {
                        "required_types": ["Spacecraft"],
                        "required_fields": {"Spacecraft": ["SMA", "INC"]},
                        "required_commands": ["Propagate"],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (prompt,) = load_prompts(path)
    assert prompt.difficulty == "hard"
    assert prompt.structural.required_types == ("Spacecraft",)
    assert prompt.structural.required_fields == {"Spacecraft": ("SMA", "INC")}
    assert prompt.structural.required_commands == ("Propagate",)


def test_shipped_suite_is_well_formed_and_stratified() -> None:
    prompts = load_prompts(SUITE)
    assert len(prompts) >= 50
    ids = [p.id for p in prompts]
    assert len(ids) == len(set(ids)), "duplicate prompt ids"
    tiers = collections.Counter(p.difficulty for p in prompts)
    # The suite spans all three difficulty tiers (decision D6 aggregates per tier).
    assert set(tiers) == {"easy", "medium", "hard"}
    assert all(count > 0 for count in tiers.values())
    for prompt in prompts:
        assert prompt.request and prompt.intent  # every prompt carries a request and an intent
