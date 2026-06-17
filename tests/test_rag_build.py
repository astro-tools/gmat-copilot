"""Build-time corpus extraction: ingest, chunk, embed, write (decisions D2/D3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from gmat_script import load_catalog

from gmat_copilot.rag import Embedder, build, load_corpus
from gmat_copilot.rag.schema import CorpusChunk


def test_ingest_help_splits_sections_and_drops_nav(rag_fixture: Path) -> None:
    chunks = build.ingest_help(rag_fixture / "docs" / "help" / "html")
    sections = {c.section for c in chunks}
    assert {"Description", "Fields", "Remarks"} <= sections
    assert all(c.kind == "help" and c.origin == "SampleResource.html" for c in chunks)
    # Each section chunk is tagged with its resource title so retrieval knows what it documents.
    assert all(c.text.startswith("SampleResource — ") for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    assert "SampleField" in joined
    # Navigation chrome must not leak into the text.
    assert not any(crumb in joined for crumb in ("PrevCrumb", "NextCrumb", "HomeCrumb"))


def test_ingest_samples_splits_on_banners(rag_fixture: Path) -> None:
    chunks = build.ingest_samples(rag_fixture / "samples")
    sections = {c.section for c in chunks}
    assert {"Spacecraft", "Propagators"} <= sections
    assert all(c.kind == "sample" and c.origin == "ex_sample.script" for c in chunks)
    spacecraft = next(c for c in chunks if c.section == "Spacecraft")
    assert "testSat.SMA = 7000" in spacecraft.text


def test_ingest_gmf_one_chunk_per_file(rag_fixture: Path) -> None:
    chunks = build.ingest_gmf(rag_fixture)
    assert [c.origin for c in chunks] == ["Example.gmf"]
    assert chunks[0].kind == "gmf"
    assert "GmatFunction" in chunks[0].text


def test_ingest_domain_notes(rag_fixture: Path) -> None:
    chunks = build.ingest_domain_notes(rag_fixture / "domain-notes")
    assert [c.origin for c in chunks] == ["note-modeling.md"]
    assert chunks[0].kind == "domain-note"
    assert chunks[0].text.startswith("# Example modeling note")


def test_ingest_domain_notes_missing_dir_is_empty(tmp_path: Path) -> None:
    assert build.ingest_domain_notes(tmp_path / "nope") == []


def test_ingest_catalogue_from_real_catalog() -> None:
    chunks = build.ingest_catalogue(load_catalog())
    assert chunks, "catalogue ingest produced no chunks"
    assert all(c.kind == "catalogue" for c in chunks)
    burn = next((c for c in chunks if c.origin == "ImpulsiveBurn"), None)
    assert burn is not None
    # The Axes enum is the canonical structured-field signal for this type.
    assert "Axes" in burn.text and "VNB" in burn.text


def test_collect_chunks_covers_all_tiers(rag_fixture: Path) -> None:
    chunks = build.collect_chunks(
        rag_fixture, notes_dir=rag_fixture / "domain-notes", catalog=load_catalog()
    )
    assert {c.kind for c in chunks} == {"help", "sample", "gmf", "catalogue", "domain-note"}


def test_collect_chunks_missing_sources_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build.collect_chunks(tmp_path, notes_dir=tmp_path, catalog=load_catalog())


def test_write_corpus_roundtrips(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [
        CorpusChunk("set the spacecraft semi-major axis and eccentricity", "domain-note", "a.md"),
        CorpusChunk("apply an impulsive maneuver delta-v in the VNB frame", "domain-note", "b.md"),
        CorpusChunk("write an ephemeris file in CCSDS OEM format", "domain-note", "c.md"),
    ]
    manifest = build.write_corpus(
        chunks, out_dir=tmp_path, embedder=fake_embedder, gmat_version="test"
    )
    assert manifest["n_chunks"] == 3
    assert manifest["dim"] == fake_embedder.dim
    assert manifest["embedder"] == fake_embedder.name
    assert manifest["chunks_by_kind"] == {"domain-note": 3}
    for name in ("corpus.jsonl", "index.faiss", "manifest.json"):
        assert (tmp_path / name).exists()

    index = load_corpus(fake_embedder, corpus_dir=tmp_path)
    assert len(index) == 3
    hits = index.search("apply an impulsive maneuver in the VNB frame", embedder=fake_embedder, k=1)
    assert hits and hits[0].chunk.origin == "b.md"


def test_write_corpus_empty_raises(tmp_path: Path, fake_embedder: Embedder) -> None:
    with pytest.raises(ValueError):
        build.write_corpus([], out_dir=tmp_path, embedder=fake_embedder, gmat_version="test")
