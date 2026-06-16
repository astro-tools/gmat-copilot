"""The deterministic structural scorer (decision D6).

The first of the two scoring layers: GMAT-free, instant, reproducible. It settles what it can with
``gmat-script`` — the lint ceiling (no ERROR or WARNING) plus the required resource types, fields,
and commands from a prompt's :class:`~gmat_copilot.eval.prompts.StructuralSpec`. The semantic
residual is left to the LLM judge.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from gmat_script import Script, Severity, lint

from .prompts import StructuralSpec

__all__ = ["StructuralResult", "structural_score"]


@dataclass(frozen=True, slots=True)
class StructuralResult:
    """The structural verdict for one candidate script and the specific checks it failed."""

    passed: bool
    failures: tuple[str, ...] = ()


def _command_keywords(script: Script) -> set[str]:
    """Every command keyword in the mission sequence, descending into control-flow bodies."""
    keywords: set[str] = set()

    def walk(commands: Iterable[Any]) -> None:
        for command in commands:
            keyword = getattr(command, "keyword", "")
            if keyword:
                keywords.add(keyword)
            body = getattr(command, "body", None)
            if body:
                walk(body)

    walk(script.mission_sequence)
    return keywords


def structural_score(script_text: str, spec: StructuralSpec) -> StructuralResult:
    """Score *script_text* against *spec* with the deterministic structural checks."""
    failures: list[str] = []

    blocking = sorted(
        {d.rule for d in lint(script_text) if d.severity in (Severity.ERROR, Severity.WARNING)}
    )
    if blocking:
        failures.append("lint:" + ",".join(blocking))

    script = Script.parse(script_text)
    present_types = {resource.type for resource in script.resources.values()}
    for required_type in spec.required_types:
        if required_type not in present_types:
            failures.append(f"missing-type:{required_type}")

    for required_type, fields in spec.required_fields.items():
        matching = [r for r in script.resources.values() if r.type == required_type]
        for required_field in fields:
            if not any(required_field in resource for resource in matching):
                failures.append(f"missing-field:{required_type}.{required_field}")

    keywords = _command_keywords(script)
    for command in spec.required_commands:
        if command not in keywords:
            failures.append(f"missing-command:{command}")

    return StructuralResult(passed=not failures, failures=tuple(failures))
