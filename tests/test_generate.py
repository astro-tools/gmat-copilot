"""``draft`` orchestration: the strict/permissive gate against a stubbed retriever + provider.

The retriever and the live provider land with later feature work; here they are stand-ins so the
orchestration, the result assembly, and the lint gate (decision D5) are testable today. Validation
runs the real ``validate`` against committed valid / invalid scripts — the lint outcome is driven by
the script the stub provider returns, not by faking the validator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_copilot import CopilotResult, DraftRejected, draft
from gmat_copilot.providers import Completion, Provider, ProviderError
from gmat_copilot.rag import Retriever
from gmat_copilot.result import RetrievalChunk, RetrievalTrace


class StubRetriever(Retriever):
    """Returns a fixed trace without touching the (unbuilt) index."""

    def __init__(self, chunks: tuple[RetrievalChunk, ...] = ()) -> None:
        super().__init__()
        self._chunks = chunks

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        return RetrievalTrace(chunks=self._chunks)


class StubProvider:
    """Returns a fixed script — a model stand-in that structurally satisfies ``Provider``."""

    name = "stub"

    def __init__(self, script: str) -> None:
        self._script = script

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        return Completion(
            text=self._script, provider=self.name, model=model, usage={"total_tokens": 1}
        )


def test_stub_provider_satisfies_the_protocol(valid_script: str) -> None:
    assert isinstance(StubProvider(valid_script), Provider)


def test_strict_returns_a_clean_result(valid_script: str) -> None:
    result = draft(
        "a 500 km LEO",
        model="stub-model",
        provider=StubProvider(valid_script),
        retriever=StubRetriever(),
    )
    assert isinstance(result, CopilotResult)
    assert result.script == valid_script
    assert result.lint.clean
    assert result.provider == "stub"
    assert result.model == "stub-model"
    assert result.usage == {"total_tokens": 1}


def test_strict_rejects_an_unclean_draft(invalid_script: str) -> None:
    with pytest.raises(DraftRejected) as excinfo:
        draft(
            "a broken mission",
            model="m",
            provider=StubProvider(invalid_script),
            retriever=StubRetriever(),
        )
    # The rejected result is attached for inspection rather than discarded.
    rejected = excinfo.value.result
    assert rejected.script == invalid_script
    assert not rejected.lint.clean
    assert rejected.lint.blocking(strict=True)


def test_permissive_returns_an_unclean_draft_with_diagnostics(invalid_script: str) -> None:
    result = draft(
        "a broken mission",
        model="m",
        strict=False,
        provider=StubProvider(invalid_script),
        retriever=StubRetriever(),
    )
    assert result.script == invalid_script
    assert not result.lint.clean
    assert result.lint.diagnostics  # attached, not raised


def test_retrieval_trace_flows_into_the_result(valid_script: str) -> None:
    chunks = (RetrievalChunk(source="help/Spacecraft.html", score=0.9, text="Create Spacecraft"),)
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=StubProvider(valid_script),
        retriever=StubRetriever(chunks),
    )
    assert result.retrieval.chunks == chunks


def test_drafted_script_saves_to_disk(tmp_path: Path, valid_script: str) -> None:
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=StubProvider(valid_script),
        retriever=StubRetriever(),
    )
    out = result.save(tmp_path / "mission.script")
    assert out.read_text(encoding="utf-8") == valid_script


def test_no_model_and_no_provider_errors_per_d4() -> None:
    with pytest.raises(ProviderError) as excinfo:
        draft("anything")
    assert "no model selected" in str(excinfo.value).lower()


def test_injected_provider_still_requires_a_model(valid_script: str) -> None:
    with pytest.raises(ValueError, match="model is required"):
        draft("x", provider=StubProvider(valid_script), retriever=StubRetriever())
