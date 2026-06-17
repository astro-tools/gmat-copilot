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
from gmat_copilot.generate import _compose_prompt
from gmat_copilot.providers import (
    Completion,
    Provider,
    ProviderError,
    RecordedProvider,
    prompt_key,
)
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
        self.last_prompt: str | None = None

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        self.last_prompt = prompt
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


def test_strict_rejects_a_hallucinated_field_on_a_warning(hallucinated_field_script: str) -> None:
    # The DoD's headline case: a hallucinated field lints only as a WARNING, yet strict must still
    # reject it (D5) — distinct from the parse-ERROR path above.
    with pytest.raises(DraftRejected) as excinfo:
        draft(
            "a LEO with a mistyped field",
            model="m",
            provider=StubProvider(hallucinated_field_script),
            retriever=StubRetriever(),
        )
    rejected = excinfo.value.result
    assert rejected.lint.warnings  # rejected on a warning, not an error
    assert rejected.lint.errors == ()
    assert rejected.lint.blocking(strict=True)


def test_permissive_warns_on_a_hallucinated_field(hallucinated_field_script: str) -> None:
    result = draft(
        "a LEO with a mistyped field",
        model="m",
        strict=False,
        provider=StubProvider(hallucinated_field_script),
        retriever=StubRetriever(),
    )
    assert result.script == hallucinated_field_script
    assert result.lint.warnings  # attached, not raised
    assert result.lint.blocking(strict=False) == ()


def test_strict_rejects_a_hallucinated_resource(hallucinated_resource_script: str) -> None:
    with pytest.raises(DraftRejected) as excinfo:
        draft(
            "a LEO with an invented resource type",
            model="m",
            provider=StubProvider(hallucinated_resource_script),
            retriever=StubRetriever(),
        )
    assert excinfo.value.result.lint.errors


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


def test_prompt_pins_the_output_contract_and_includes_grounding(valid_script: str) -> None:
    chunks = (
        RetrievalChunk(
            source="GMAT sample: ex_leo.script", score=0.9, text="Create Spacecraft Sat;"
        ),
    )
    provider = StubProvider(valid_script)
    draft("a 500 km circular LEO", model="m", provider=provider, retriever=StubRetriever(chunks))

    prompt = provider.last_prompt
    assert prompt is not None
    # The intent and the retrieved grounding (text + source label) both reach the model.
    assert "a 500 km circular LEO" in prompt
    assert "Create Spacecraft Sat;" in prompt
    assert "GMAT sample: ex_leo.script" in prompt
    # The output contract is pinned: a fenced .script, resources before use, no prose.
    assert "```script" in prompt
    assert "BeginMissionSequence" in prompt
    assert "no prose" in prompt.lower()


def test_prompt_omits_grounding_when_retrieval_is_empty(valid_script: str) -> None:
    provider = StubProvider(valid_script)
    draft("anything", model="m", provider=provider, retriever=StubRetriever())

    prompt = provider.last_prompt
    assert prompt is not None
    assert "# Grounding context" not in prompt
    # The contract is still pinned without any grounding.
    assert "```script" in prompt
    assert "anything" in prompt


def test_fenced_completion_is_unwrapped_to_the_script(valid_script: str) -> None:
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=StubProvider(f"```script\n{valid_script}```"),
        retriever=StubRetriever(),
    )
    assert result.script == valid_script.strip()
    assert result.lint.clean


def test_fenced_extraction_ignores_surrounding_prose(valid_script: str) -> None:
    noisy = "Here is your mission script:\n\n```\n" + valid_script + "```\n\nHope that helps!"
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=StubProvider(noisy),
        retriever=StubRetriever(),
    )
    assert result.script == valid_script.strip()
    assert result.lint.clean


def test_unfenced_completion_passes_through_verbatim(valid_script: str) -> None:
    result = draft(
        "a 500 km LEO",
        model="m",
        provider=StubProvider(valid_script),
        retriever=StubRetriever(),
    )
    # No fence: returned byte-for-byte, including the trailing newline.
    assert result.script == valid_script


def test_recorded_provider_drives_draft_deterministically(valid_script: str) -> None:
    request = "a 500 km circular LEO"
    chunks = (
        RetrievalChunk(
            source="GMAT sample: ex_leo.script", score=0.9, text="Create Spacecraft Sat;"
        ),
    )
    retriever = StubRetriever(chunks)
    model = "openai/gpt-4.1-mini"
    # Key the fixture on the exact prompt draft() composes, with the script fenced per the contract.
    prompt = _compose_prompt(request, RetrievalTrace(chunks=chunks))
    fixtures = {
        prompt_key("github", model, prompt): {
            "text": f"```script\n{valid_script}```",
            "usage": {"total_tokens": 7},
        }
    }
    provider = RecordedProvider(fixtures)

    first = draft(request, model=model, provider=provider, retriever=retriever)
    second = draft(request, model=model, provider=provider, retriever=retriever)

    assert first.script == second.script == valid_script.strip()
    assert first.lint.clean
    assert first.provider == "recorded"
    assert first.usage == {"total_tokens": 7}
