"""The deterministic structural scorer (decision D6): lint ceiling + required types/fields/commands.

Runs the real ``gmat-script`` linter and parser — the structural layer is GMAT-free and
deterministic, so there is nothing to stub.
"""

from __future__ import annotations

from gmat_copilot.eval import structural_score
from gmat_copilot.eval.prompts import StructuralSpec

# A script with a Target block, so the command walk has to descend into a control-flow body.
TARGET_SCRIPT = """
Create Spacecraft Sat;
Create ImpulsiveBurn dv;
dv.Axes = VNB;
Create DifferentialCorrector DC;
Create Propagator Prop;
Create ForceModel FM;
Prop.FM = FM;
BeginMissionSequence;
Target DC;
   Vary DC(dv.Element1 = 0.1);
   Maneuver dv(Sat);
   Propagate Prop(Sat) {Sat.Apoapsis};
   Achieve DC(Sat.Earth.RMAG = 8000);
EndTarget;
"""


def test_passes_when_the_spec_is_met(valid_script: str) -> None:
    spec = StructuralSpec(
        required_types=("Spacecraft", "Propagator", "ReportFile"),
        required_fields={"Spacecraft": ("SMA", "ECC", "INC")},
        required_commands=("Propagate", "Report"),
    )
    result = structural_score(valid_script, spec)
    assert result.passed
    assert result.failures == ()


def test_missing_type_is_a_failure(valid_script: str) -> None:
    result = structural_score(valid_script, StructuralSpec(required_types=("EphemerisFile",)))
    assert not result.passed
    assert "missing-type:EphemerisFile" in result.failures


def test_missing_field_is_a_failure(valid_script: str) -> None:
    result = structural_score(
        valid_script, StructuralSpec(required_fields={"Spacecraft": ("DryMass",)})
    )
    assert "missing-field:Spacecraft.DryMass" in result.failures


def test_missing_command_is_a_failure(valid_script: str) -> None:
    result = structural_score(valid_script, StructuralSpec(required_commands=("Maneuver",)))
    assert "missing-command:Maneuver" in result.failures


def test_blocking_lint_fails_structurally(hallucinated_resource_script: str) -> None:
    # An unknown resource type is a lint ERROR -> a structural failure regardless of presence.
    result = structural_score(hallucinated_resource_script, StructuralSpec())
    assert not result.passed
    assert any(f.startswith("lint:") for f in result.failures)


def test_warning_level_lint_also_blocks(hallucinated_field_script: str) -> None:
    # A hallucinated field is only a WARNING, but D5 blocks on warnings too.
    result = structural_score(hallucinated_field_script, StructuralSpec())
    assert not result.passed
    assert any(f.startswith("lint:") for f in result.failures)


def test_command_walk_descends_into_control_flow_bodies() -> None:
    # Vary / Maneuver / Achieve live inside the Target block; the walk must find them.
    spec = StructuralSpec(
        required_types=("DifferentialCorrector", "ImpulsiveBurn"),
        required_commands=("Target", "Vary", "Maneuver", "Achieve"),
    )
    result = structural_score(TARGET_SCRIPT, spec)
    assert result.passed, result.failures


def test_unparseable_output_fails_without_raising() -> None:
    # A model that emits prose instead of a script must score as a clean structural FAIL, not crash.
    result = structural_score(
        "I cannot write that script.", StructuralSpec(required_types=("Spacecraft",))
    )
    assert not result.passed
    assert "missing-type:Spacecraft" in result.failures
