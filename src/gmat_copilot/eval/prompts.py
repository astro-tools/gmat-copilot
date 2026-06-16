"""The eval prompt set and its checkable specs (decision D6).

Each prompt pairs a natural-language *request* with an *intent* string (what the judge scores) and a
*structural* spec: the lint ceiling plus the resource types, fields, and commands a satisfying
script must contain. The full set is built by the eval-suite work; this module defines the schema
and the loader.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["EvalPrompt", "StructuralSpec", "load_prompts"]


@dataclass(frozen=True, slots=True)
class StructuralSpec:
    """What the deterministic structural layer asserts about a candidate script."""

    required_types: tuple[str, ...] = ()
    required_fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    required_commands: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalPrompt:
    """One eval prompt: the request sent to the model, its intent, and its structural spec."""

    id: str
    request: str
    intent: str
    structural: StructuralSpec
    difficulty: str = "easy"


def load_prompts(path: str | Path) -> list[EvalPrompt]:
    """Load an eval prompt set from a JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    prompts: list[EvalPrompt] = []
    for entry in raw:
        spec = entry.get("structural", {})
        prompts.append(
            EvalPrompt(
                id=entry["id"],
                request=entry["request"],
                intent=entry["intent"],
                difficulty=entry.get("difficulty", "easy"),
                structural=StructuralSpec(
                    required_types=tuple(spec.get("required_types", [])),
                    required_fields={
                        k: tuple(v) for k, v in spec.get("required_fields", {}).items()
                    },
                    required_commands=tuple(spec.get("required_commands", [])),
                ),
            )
        )
    return prompts
