"""The embedding-model abstraction (decision D2).

Passages and queries are embedded with a BGE-class sentence-transformer; the default is
``bge-small-en-v1.5`` (MIT, 384-dim). The model is imported and loaded lazily so importing the
package stays light and GMAT-free, and the embedder is a small protocol so the build and
fallback-rebuild paths can be exercised with an injected stand-in instead of the real model.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

__all__ = ["DEFAULT_EMBEDDER", "BgeEmbedder", "Embedder"]

DEFAULT_EMBEDDER = "BAAI/bge-small-en-v1.5"

# BGE retrieval convention: prefix the *query* (not the passages) with this instruction.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@runtime_checkable
class Embedder(Protocol):
    """Embeds passages and queries into a shared vector space.

    Implementations normalise their output so a flat inner-product index measures cosine similarity.
    """

    name: str

    @property
    def dim(self) -> int:
        """The embedding dimension."""

    def encode(self, texts: Sequence[str], *, is_query: bool = False) -> NDArray[np.float32]:
        """Embed *texts*, returning one row per text. Set ``is_query`` for retrieval queries."""
        ...


class BgeEmbedder:
    """The default :class:`Embedder`: a lazily-loaded BGE sentence-transformer.

    ``sentence_transformers`` is imported on first use, not at construction, so neither importing
    the package nor loading the shipped index (built for this model) pays the model-load cost.
    """

    def __init__(self, name: str = DEFAULT_EMBEDDER) -> None:
        self.name = name
        self._model: Any = None
        self._dim: int | None = None

    def _ensure(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name)
            # Method was renamed across sentence-transformers majors; prefer the current name.
            dim_fn = getattr(self._model, "get_embedding_dimension", None)
            if dim_fn is None:
                dim_fn = self._model.get_sentence_embedding_dimension
            self._dim = int(dim_fn())
        return self._model

    @property
    def dim(self) -> int:
        self._ensure()
        assert self._dim is not None
        return self._dim

    def encode(self, texts: Sequence[str], *, is_query: bool = False) -> NDArray[np.float32]:
        model = self._ensure()
        items = [_BGE_QUERY_PREFIX + t for t in texts] if is_query else list(texts)
        vectors = model.encode(
            items, normalize_embeddings=True, batch_size=64, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)
