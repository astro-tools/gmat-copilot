"""The default BGE embedder: lazy model load and BGE query/passage encoding (decision D2).

The real ``sentence_transformers`` model is never downloaded; a stand-in is injected via
``sys.modules`` so the encode/normalise/dimension logic runs offline and deterministically.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Sequence

import numpy as np
import pytest
from numpy.typing import NDArray

from gmat_copilot.rag.embed import _BGE_QUERY_PREFIX, BgeEmbedder


class _FakeModel:
    """A minimal SentenceTransformer stand-in that records its encode calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def get_embedding_dimension(self) -> int:
        return 8

    def encode(self, items: Sequence[str], **kwargs: object) -> NDArray[np.float64]:
        self.calls.append((list(items), kwargs))
        return np.ones((len(items), 8), dtype=np.float64)


class _LegacyModel(_FakeModel):
    """An older SentenceTransformer that only exposes the pre-rename dimension method."""

    get_embedding_dimension = None  # type: ignore[assignment]

    def get_sentence_embedding_dimension(self) -> int:
        return 5


def _install(monkeypatch: pytest.MonkeyPatch, model_cls: type[_FakeModel]) -> None:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = model_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


def test_dim_loads_the_model_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeModel)
    embedder = BgeEmbedder("some-model")
    assert embedder.dim == 8
    # Loaded once and cached: a second read does not reconstruct the model.
    assert embedder.dim == 8


def test_dim_falls_back_to_the_legacy_method(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _LegacyModel)
    assert BgeEmbedder("legacy").dim == 5


def test_encode_prefixes_queries_and_returns_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeModel)
    embedder = BgeEmbedder()
    model: _FakeModel = embedder._ensure()  # the stand-in we just injected

    passages = embedder.encode(["alpha", "beta"])
    queries = embedder.encode(["find me"], is_query=True)

    assert passages.dtype == np.float32
    assert passages.shape == (2, 8)
    assert queries.dtype == np.float32
    # Passages go in verbatim; the query carries the BGE retrieval instruction prefix.
    passage_items, passage_kwargs = model.calls[0]
    query_items, _ = model.calls[1]
    assert passage_items == ["alpha", "beta"]
    assert query_items == [_BGE_QUERY_PREFIX + "find me"]
    # Output is normalised for an inner-product (cosine) index.
    assert passage_kwargs["normalize_embeddings"] is True
