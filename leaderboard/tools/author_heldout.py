#!/usr/bin/env python3
"""Scaffold a never-committed held-out prompt set for the leaderboard headline (decision D16).

The board ranks on a private held-out set whose golds live only in a private store and are *never*
committed. This helper writes a ``prompts.json`` skeleton — placeholder requests/intents and a
structural-spec template mirroring the committed public set — into a gitignored draft directory, so
the maintainer can author a fresh held-out (a new one is authored on every eval-protocol bump). It
embeds no golds and writes nothing under the tracked tree.

Workflow (see ``leaderboard/HOSTING.md`` for the full runbook):

1. ``python leaderboard/tools/author_heldout.py --count 12``
2. Edit the draft ``prompts.json`` into real, never-before-seen held-out prompts.
3. Record a bundle per seed model with ``gmat-copilot eval --record`` against the draft prompts.
4. Upload the recorded bundles to the private HF Dataset and set the ``LEADERBOARD_HELDOUT_DATASET``
   repository variable; the gated CI leaderboard job fetches and scores them.

The draft never enters the repository: the default output is under ``leaderboard/.cache/``
(gitignored) and the recorded bundles must be uploaded to the private store, not committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PROMPTS = REPO_ROOT / "tests" / "data" / "eval" / "prompts.json"
DEFAULT_OUT = REPO_ROOT / "leaderboard" / ".cache" / "heldout-draft"

# A neutral structural-spec skeleton in the committed schema's shape. The maintainer replaces every
# value with the real, never-published held-out spec; the skeleton only fixes the format.
_SPEC_TEMPLATE: dict[str, Any] = {
    "required_types": ["Spacecraft", "Propagator", "ReportFile"],
    "required_fields": {"Spacecraft": ["SMA", "ECC", "INC"]},
    "required_commands": ["Propagate", "Report"],
}

_PLACEHOLDER = "TODO-HELDOUT (author a real, never-published prompt here; never commit)"


def _tier_cycle(reference: list[dict[str, Any]]) -> list[str]:
    """The difficulty tiers seen in the public set, to mirror its spread in the draft."""
    tiers = [str(p.get("difficulty", "medium")) for p in reference]
    seen: list[str] = []
    for tier in tiers:
        if tier not in seen:
            seen.append(tier)
    return seen or ["easy", "medium", "hard"]


def scaffold(count: int, reference: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tiers = _tier_cycle(reference)
    return [
        {
            "id": f"ho_{i:03d}",
            "difficulty": tiers[i % len(tiers)],
            "request": _PLACEHOLDER,
            "intent": _PLACEHOLDER,
            "structural": json.loads(json.dumps(_SPEC_TEMPLATE)),
        }
        for i in range(1, count + 1)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--count", type=int, default=12, help="how many prompts to scaffold")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="draft dir (gitignored)")
    parser.add_argument(
        "--reference", type=Path, default=PUBLIC_PROMPTS, help="public prompts to mirror"
    )
    args = parser.parse_args(argv)

    if args.count < 1:
        print("author_heldout: --count must be >= 1", file=sys.stderr)
        return 2
    try:
        reference = json.loads(args.reference.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"author_heldout: cannot read reference {args.reference}: {exc}", file=sys.stderr)
        return 2

    out_file = args.out / "prompts.json"
    if out_file.exists():
        print(f"author_heldout: {out_file} exists; refusing to overwrite a draft", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    prompts = scaffold(args.count, reference)
    out_file.write_text(json.dumps(prompts, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {len(prompts)} placeholder prompt(s) to {out_file}")
    print("NEXT: edit into real held-out prompts, record a bundle per seed model, then upload")
    print("      the recorded bundles to the private HF Dataset. Golds are NEVER committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
