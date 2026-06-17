"""Query-time retrieval: ranking, trace, token budget, and context assembly (D2)."""

from __future__ import annotations

from pathlib import Path

from gmat_copilot.rag import Embedder, Retriever, assemble_context, build
from gmat_copilot.rag.schema import CorpusChunk
from gmat_copilot.result import RetrievalChunk, RetrievalTrace

_SEMANTIC = [
    CorpusChunk("set the spacecraft semi-major axis and eccentricity", "domain-note", "a.md"),
    CorpusChunk("apply an impulsive maneuver delta-v in the VNB frame", "domain-note", "b.md"),
    CorpusChunk("write an ephemeris file in CCSDS OEM format", "domain-note", "c.md"),
]


def _retriever(
    tmp_path: Path, embedder: Embedder, chunks: list[CorpusChunk], **kwargs: int
) -> Retriever:
    build.write_corpus(chunks, out_dir=tmp_path, embedder=embedder, gmat_version="test")
    return Retriever(embedder, corpus_dir=tmp_path, **kwargs)


def test_retrieve_ranks_and_records_trace(tmp_path: Path, fake_embedder: Embedder) -> None:
    retriever = _retriever(tmp_path, fake_embedder, _SEMANTIC)
    trace = retriever.retrieve("apply an impulsive maneuver in the VNB frame")
    assert isinstance(trace, RetrievalTrace)
    assert trace.chunks
    top = trace.chunks[0]
    assert "impulsive maneuver" in top.text
    assert top.source == "Domain note: b.md"
    assert isinstance(top.score, float)


def test_retrieval_is_deterministic(tmp_path: Path, fake_embedder: Embedder) -> None:
    retriever = _retriever(tmp_path, fake_embedder, _SEMANTIC)
    first = retriever.retrieve("impulsive maneuver VNB frame")
    second = retriever.retrieve("impulsive maneuver VNB frame")
    assert [(c.source, c.score, c.text) for c in first.chunks] == [
        (c.source, c.score, c.text) for c in second.chunks
    ]


def test_source_labels_are_tier_aware(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [
        CorpusChunk(
            "impulsive burn axes coordinate system fields", "help", "ImpulsiveBurn.html", "Fields"
        ),
        CorpusChunk(
            "model an impulsive maneuver with a burn", "domain-note", "intent-impulsive-maneuver.md"
        ),
    ]
    retriever = _retriever(tmp_path, fake_embedder, chunks, top_k=2)
    trace = retriever.retrieve("impulsive maneuver burn")
    assert {c.source for c in trace.chunks} == {
        "GMAT help: ImpulsiveBurn.html — Fields",
        "Domain note: intent-impulsive-maneuver.md",
    }


def test_token_budget_truncates_keeping_at_least_one(
    tmp_path: Path, fake_embedder: Embedder
) -> None:
    # Each chunk is ~60 estimated tokens; a 30-token budget admits only the top hit.
    chunks = [
        CorpusChunk(f"{word} " * 40, "domain-note", f"{i}.md")
        for i, word in enumerate(["alpha", "beta", "gamma", "delta"])
    ]
    retriever = _retriever(tmp_path, fake_embedder, chunks, top_k=8, token_budget=30)
    assert len(retriever.retrieve("alpha beta gamma delta").chunks) == 1


def test_large_budget_keeps_all_up_to_top_k(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [
        CorpusChunk(f"chunk {i} about orbits and burns", "domain-note", f"{i}.md") for i in range(4)
    ]
    retriever = _retriever(tmp_path, fake_embedder, chunks, top_k=8, token_budget=100_000)
    assert len(retriever.retrieve("orbits and burns").chunks) == 4


def test_top_k_override(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [
        CorpusChunk(f"chunk number {i} about orbits", "domain-note", f"{i}.md") for i in range(5)
    ]
    retriever = _retriever(tmp_path, fake_embedder, chunks, top_k=8, token_budget=100_000)
    assert len(retriever.retrieve("orbits", top_k=2).chunks) == 2


def test_pins_a_worked_example_below_the_budget_cut(
    tmp_path: Path, fake_embedder: Embedder
) -> None:
    # Three high-relevance definition chunks crowd out a low-relevance worked example. Without the
    # pin the budget keeps only the definitions (no command syntax); the pin retains the example.
    defn = "spacecraft orbit altitude semi major axis eccentricity inclination"
    chunks = [
        CorpusChunk(f"{defn} one", "help", "a.html", "Fields"),
        CorpusChunk(f"{defn} two", "help", "b.html", "Fields"),
        CorpusChunk(f"{defn} three", "help", "c.html", "Fields"),
        CorpusChunk(
            "BeginMissionSequence Propagate Prop(Sat) {Sat.ElapsedDays = 1}; Report rf Sat.X",
            "sample",
            "Ex_Demo.script",
            "Mission Sequence",
        ),
    ]
    retriever = _retriever(tmp_path, fake_embedder, chunks, top_k=8, token_budget=50)
    trace = retriever.retrieve(defn)
    texts = [c.text for c in trace.chunks]
    assert any("BeginMissionSequence" in t for t in texts)  # the worked example is pinned in
    assert any("eccentricity inclination" in t for t in texts)  # a top definition is still kept
    # The pinned example outranks nothing — it is appended despite the lowest relevance score.
    assert trace.chunks[-1].score == min(c.score for c in trace.chunks)


def test_worked_example_in_top_k_is_not_duplicated(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [
        CorpusChunk(
            "BeginMissionSequence Propagate Prop(Sat) {Sat.ElapsedDays = 1}; Report rf",
            "sample",
            "Ex.script",
            "Mission Sequence",
        ),
        CorpusChunk("spacecraft fields semi major axis", "help", "a.html"),
    ]
    retriever = _retriever(tmp_path, fake_embedder, chunks, top_k=8, token_budget=100_000)
    trace = retriever.retrieve("BeginMissionSequence Propagate Report")
    # When the worked example is already a top hit it is kept once, not pinned a second time.
    assert sum("BeginMissionSequence" in c.text for c in trace.chunks) == 1
    assert len(trace.chunks) == 2


def test_assemble_context_formats_with_attribution() -> None:
    trace = RetrievalTrace(
        chunks=(
            RetrievalChunk(
                source="GMAT help: ImpulsiveBurn.html — Fields", score=0.9, text="axes and elements"
            ),
            RetrievalChunk(source="Domain note: note.md", score=0.5, text="model the burn"),
        )
    )
    context = assemble_context(trace)
    assert "[GMAT help: ImpulsiveBurn.html — Fields]\naxes and elements" in context
    assert "[Domain note: note.md]\nmodel the burn" in context
    assert context.count("\n\n") == 1  # one blank line between the two blocks


def test_assemble_context_empty_trace() -> None:
    assert assemble_context(RetrievalTrace()) == ""
