"""The versioned provenance record and its ``.copilot.json`` sidecar (decision D14).

GMAT-free throughout: ``draft`` is driven by a deterministic sequence provider and a stub retriever,
and the dynamic dry-run tier is monkeypatched where a draft needs one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import SequenceProvider, StubRetriever
from gmat_copilot import (
    CopilotResult,
    LintReport,
    Provenance,
    RetrievalChunk,
    RetrievalTrace,
    draft,
    read_sidecar,
)
from gmat_copilot import repair as repair_mod
from gmat_copilot.provenance import (
    SCHEMA_VERSION,
    dumps,
    from_json_dict,
    sidecar_path,
    to_json_dict,
    write_sidecar,
)
from gmat_copilot.result import DryRunReport

_TOP_LEVEL_KEYS = {
    "schema_version",
    "request",
    "provider",
    "model",
    "retrieval",
    "drafts",
    "outcome",
}


def _chunks() -> tuple[RetrievalChunk, ...]:
    return (
        RetrievalChunk(
            source="help/Spacecraft", score=0.5, text="A Spacecraft models the satellite."
        ),
        RetrievalChunk(source="samples/leo", score=0.25, text="Create Spacecraft Sat;"),
    )


# ------------------------------------------------------------------------------------- population


def test_single_pass_populates_the_record(valid_script: str) -> None:
    provider = SequenceProvider([valid_script])
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=provider,
        retriever=StubRetriever(_chunks()),
        repair=0,
    )
    prov = result.provenance
    assert isinstance(prov, Provenance)
    assert prov.schema_version == SCHEMA_VERSION
    assert prov.request == "a 500 km LEO"  # the original intent, not a repair-augmented prompt
    assert prov.provider == "sequence"
    assert prov.model == "m"
    assert prov.retrieval.chunks == _chunks()
    assert len(prov.repair.attempts) == 1
    assert prov.repair.stop_reason == "clean"
    assert prov.outcome.winner == 0
    assert prov.outcome.passed is True
    assert prov.outcome.strict is True
    assert prov.outcome.usage == result.usage


def test_repair_history_lands_in_the_record(invalid_script: str, valid_script: str) -> None:
    provider = SequenceProvider([invalid_script, valid_script])
    result = draft("a LEO", model="m", provider=provider, retriever=StubRetriever(), repair=2)
    prov = result.provenance
    assert isinstance(prov, Provenance)
    # One entry per loop iteration: the failing draft and the repaired one (decision D13).
    assert len(prov.repair.attempts) == 2
    assert prov.repair.attempts[0].passed is False
    assert prov.repair.attempts[0].feedback_tier == "lint"
    assert prov.repair.attempts[1].passed is True
    assert prov.outcome.winner == 1  # the final (returned) draft


def test_permissive_mode_is_recorded_in_the_outcome(invalid_script: str) -> None:
    provider = SequenceProvider([invalid_script])
    result = draft(
        "broken", model="m", strict=False, provider=provider, retriever=StubRetriever(), repair=0
    )
    prov = result.provenance
    assert isinstance(prov, Provenance)
    # A permissive best-effort return: not passed, but not raised — distinguishable from a strict
    # rejection (which carries strict=True) by the recorded mode.
    assert prov.outcome.passed is False
    assert prov.outcome.strict is False


# ------------------------------------------------------------------------------------- round-trip


def _provenance(request: str = "a 500 km LEO", *, repair: int = 0) -> Provenance:
    provider = SequenceProvider(["X X X"])  # lint-failing is fine; we only need a populated record
    result = draft(
        request,
        model="m",
        strict=False,
        provider=provider,
        retriever=StubRetriever(_chunks()),
        repair=repair,
    )
    prov = result.provenance
    assert isinstance(prov, Provenance)
    return prov


def test_dict_round_trip_is_lossless() -> None:
    prov = _provenance(repair=1)
    assert from_json_dict(to_json_dict(prov)) == prov


def test_sidecar_round_trips(tmp_path: Path) -> None:
    prov = _provenance(repair=1)
    out = write_sidecar(prov, tmp_path / "mission.script.copilot.json")
    assert out.exists()
    assert read_sidecar(out) == prov


def test_round_trip_preserves_dry_run_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valid_script: str
) -> None:
    # Two lint-clean attempts so both dry-run shapes round-trip: a load failure with no solver
    # (converged=None) and a converged run-tier pass (converged={...}).
    calls: list[str] = []

    def fake(script: str, *, gmat_root: str | None = None, timeout: float = 300.0) -> DryRunReport:
        calls.append(script)
        if len(calls) == 1:
            return DryRunReport(
                tier="load", ok=False, converged=None, one_line="bad eccentricity", raw_log="log"
            )
        return DryRunReport(tier="run", ok=True, converged={"DC": True}, one_line="", raw_log="")

    monkeypatch.setattr(repair_mod, "_dry_run", fake)
    provider = SequenceProvider([valid_script, valid_script + "\n% revised\n"])
    result = draft(
        "a LEO", model="m", provider=provider, retriever=StubRetriever(), repair=1, dry_run=True
    )
    prov = result.provenance
    assert isinstance(prov, Provenance)
    assert prov.repair.attempts[0].dry_run is not None  # load failure, converged=None
    assert prov.repair.attempts[1].dry_run is not None  # run-tier pass, converged set
    out = result.save(tmp_path / "m.script", sidecar=True)
    reloaded = read_sidecar(sidecar_path(out))
    assert reloaded == prov
    assert reloaded.repair.attempts[0].dry_run == prov.repair.attempts[0].dry_run
    assert reloaded.repair.attempts[1].dry_run == prov.repair.attempts[1].dry_run


# ----------------------------------------------------------------------------- stable, secret-free


def test_json_is_stable_and_sorted() -> None:
    prov = _provenance(repair=1)
    text = dumps(prov)
    assert dumps(prov) == text  # deterministic run to run
    keys = list(json.loads(text).keys())
    assert keys == sorted(keys)  # sort_keys took effect — diffs cleanly
    assert text.endswith("\n")


def test_record_carries_only_the_schema_keys_no_secrets() -> None:
    # The structural no-secrets guarantee: every serialised key is one of D14's, so a credential has
    # nowhere to enter. Provider/model are names only.
    data = to_json_dict(_provenance())
    assert set(data) == _TOP_LEVEL_KEYS
    assert data["provider"] == "sequence"
    assert "key" not in dumps(_provenance()).lower()


# --------------------------------------------------------------------------------- schema version


def test_writer_stamps_the_schema_version() -> None:
    assert to_json_dict(_provenance())["schema_version"] == SCHEMA_VERSION


def test_reader_rejects_an_unsupported_version() -> None:
    data = to_json_dict(_provenance())
    data["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema_version"):
        from_json_dict(data)


def test_reader_rejects_a_missing_version() -> None:
    data = to_json_dict(_provenance())
    del data["schema_version"]
    with pytest.raises(ValueError, match="schema_version"):
        from_json_dict(data)


# ------------------------------------------------------------------------------------ save() wiring


def test_save_without_sidecar_writes_only_the_script(tmp_path: Path, valid_script: str) -> None:
    provider = SequenceProvider([valid_script])
    result = draft("a LEO", model="m", provider=provider, retriever=StubRetriever(), repair=0)
    out = result.save(tmp_path / "mission.script")
    assert out.read_text(encoding="utf-8") == valid_script
    assert not sidecar_path(out).exists()


def test_save_with_sidecar_writes_both(tmp_path: Path, valid_script: str) -> None:
    provider = SequenceProvider([valid_script])
    result = draft("a LEO", model="m", provider=provider, retriever=StubRetriever(), repair=0)
    out = result.save(tmp_path / "mission.script", sidecar=True)
    side = sidecar_path(out)
    assert side == tmp_path / "mission.script.copilot.json"
    assert out.read_text(encoding="utf-8") == valid_script
    assert read_sidecar(side) == result.provenance


def test_save_sidecar_on_a_provenance_less_result_raises(tmp_path: Path) -> None:
    result = CopilotResult(
        script="Create Spacecraft Sat;\n",
        lint=LintReport(),
        retrieval=RetrievalTrace(),
        provider="recorded",
        model="m",
    )
    target = tmp_path / "m.script"
    with pytest.raises(TypeError, match="provenance-bearing"):
        result.save(target, sidecar=True)
    # The validation must fail before any write: no orphan .script (and no sidecar) is left behind.
    assert not target.exists()
    assert not sidecar_path(target).exists()
