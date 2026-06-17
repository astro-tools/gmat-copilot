"""Runtime corpus loader: shipped-artifact load + the fallback rebuild path (decision D2)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from gmat_copilot.rag import DEFAULT_EMBEDDER, Embedder, build, load_corpus
from gmat_copilot.rag.loader import SHIPPED_CORPUS_DIR
from gmat_copilot.rag.schema import CorpusChunk


def test_load_shipped_corpus_without_a_model() -> None:
    """The shipped text + prebuilt index load with no GMAT install and no model download."""
    index = load_corpus()
    assert len(index) > 0
    assert index.dim == 384
    assert index.embedder_name == DEFAULT_EMBEDDER
    # All five corpus tiers are present, each chunk carrying provenance for the trace / attribution.
    kinds = {c.kind for c in index.chunks}
    assert {"help", "sample", "gmf", "catalogue", "domain-note"} <= kinds
    assert all(c.origin for c in index.chunks)


def test_shipped_corpus_dir_is_inside_the_package() -> None:
    # Ships as package data so a wheel install carries it.
    assert SHIPPED_CORPUS_DIR.name == "corpus"
    assert SHIPPED_CORPUS_DIR.parent.name == "rag"


def test_default_path_uses_prebuilt_index(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [CorpusChunk("propagate the orbit to apoapsis then report", "domain-note", "x.md")]
    build.write_corpus(chunks, out_dir=tmp_path, embedder=fake_embedder, gmat_version="test")
    # Embedder name matches the manifest -> prebuilt index loaded, no rebuild.
    index = load_corpus(fake_embedder, corpus_dir=tmp_path)
    assert index.embedder_name == fake_embedder.name
    assert index.dim == fake_embedder.dim


def test_none_embedder_defaults_to_manifest(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [CorpusChunk("set a point-mass earth gravity force model", "domain-note", "y.md")]
    build.write_corpus(chunks, out_dir=tmp_path, embedder=fake_embedder, gmat_version="test")
    index = load_corpus(corpus_dir=tmp_path)
    assert index.embedder_name == fake_embedder.name


def test_fallback_rebuild_caches_and_reuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_embedder: Callable[..., Embedder],
) -> None:
    cache_root = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))
    builder = make_embedder(name="builder", dim=16)
    other = make_embedder(name="other", dim=12)
    corpus_dir = tmp_path / "corpus"
    chunks = [
        CorpusChunk(
            "model a sun synchronous orbit with the right inclination", "domain-note", "p.md"
        ),
        CorpusChunk("apply a finite burn with a thruster and fuel tank", "domain-note", "q.md"),
    ]
    build.write_corpus(chunks, out_dir=corpus_dir, embedder=builder, gmat_version="test")

    # A different embedder must rebuild into its own dim and cache the index under XDG.
    index = load_corpus(other, corpus_dir=corpus_dir)
    assert index.embedder_name == "other"
    assert index.dim == 12
    cached = list(cache_root.rglob("*.index.faiss"))
    assert cached, "fallback rebuild did not cache an index"

    # A second load hits the cache (same dim, correct retrieval).
    again = load_corpus(other, corpus_dir=corpus_dir)
    assert again.dim == 12
    hits = again.search("finite burn thruster fuel tank", embedder=other, k=1)
    assert hits and hits[0].chunk.origin == "q.md"


def test_search_clamps_k_to_corpus_size(tmp_path: Path, fake_embedder: Embedder) -> None:
    chunks = [
        CorpusChunk("first chunk about coordinate systems and axes", "domain-note", "1.md"),
        CorpusChunk("second chunk about time systems and epochs", "domain-note", "2.md"),
    ]
    build.write_corpus(chunks, out_dir=tmp_path, embedder=fake_embedder, gmat_version="test")
    index = load_corpus(fake_embedder, corpus_dir=tmp_path)
    hits = index.search("coordinate systems", embedder=fake_embedder, k=50)
    assert len(hits) == 2  # k clamped to the corpus size, no padding entries
