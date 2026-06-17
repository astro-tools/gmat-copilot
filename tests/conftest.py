"""Shared test fixtures and paths."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

DATA = Path(__file__).parent / "data"


class FakeEmbedder:
    """A deterministic, model-free :class:`~gmat_copilot.rag.Embedder` for tests.

    Hashed bag-of-words vectors, normalised, so two texts sharing tokens score higher under inner
    product. Lets the ingest / build / load / fallback-rebuild paths run without downloading the
    real embedding model. Deterministic across processes (stable hash), unlike Python's salted hash.
    """

    def __init__(self, name: str = "fake-embedder", dim: int = 24) -> None:
        self.name = name
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def encode(self, texts: Sequence[str], *, is_query: bool = False) -> NDArray[np.float32]:
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in text.lower().split():
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
                out[row, int.from_bytes(digest, "big") % self._dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return cast("NDArray[np.float32]", (out / norms).astype(np.float32))


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """A default deterministic test embedder."""
    return FakeEmbedder()


@pytest.fixture
def make_embedder() -> Callable[..., FakeEmbedder]:
    """Factory for fake embedders with a chosen name/dim (e.g. to force a fallback rebuild)."""

    def _make(name: str = "fake-embedder", dim: int = 24) -> FakeEmbedder:
        return FakeEmbedder(name=name, dim=dim)

    return _make


@pytest.fixture
def rag_fixture() -> Path:
    """Root of the tiny fixture corpus (help / samples / gmf / domain-notes)."""
    return DATA / "rag_fixture"


@pytest.fixture
def valid_script() -> str:
    """A GMAT script that lints clean (no errors or warnings)."""
    return (DATA / "valid.script").read_text(encoding="utf-8")


@pytest.fixture
def invalid_script() -> str:
    """A script that fails to parse — a hard lint ERROR."""
    return (DATA / "invalid.script").read_text(encoding="utf-8")


@pytest.fixture
def hallucinated_field_script() -> str:
    """A well-formed script with a hallucinated field — a single ``unknown-field`` WARNING."""
    return (DATA / "hallucinated_field.script").read_text(encoding="utf-8")


@pytest.fixture
def hallucinated_resource_script() -> str:
    """A script with an invented resource type — a single ``unknown-resource-type`` ERROR."""
    return (DATA / "hallucinated_resource.script").read_text(encoding="utf-8")


@pytest.fixture
def eval_bundle() -> Path:
    """The committed deterministic recorded-eval bundle directory."""
    return DATA / "eval_smoke"
