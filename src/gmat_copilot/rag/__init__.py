"""Corpus ingest, the FAISS index, and the retriever (decisions D2, D3).

Retrieval grounds generation in the GMAT help pages, the stock sample scripts, the GmatFunctions,
the gmat-script field catalogue, and a curated domain-notes tier. The corpus text and a prebuilt
index for the default embedder are extracted by maintainers at build time (:mod:`.build`) and
shipped with the package; the runtime :func:`.load_corpus` loads them with no GMAT install and no
network, rebuilding the index on first use only as a fallback. ``sentence-transformers`` / ``faiss``
are imported lazily so importing the package stays light.
"""

from __future__ import annotations

from ..result import RetrievalTrace
from .embed import DEFAULT_EMBEDDER, BgeEmbedder, Embedder
from .loader import CorpusIndex, SearchHit, load_corpus
from .schema import ChunkKind, CorpusChunk

__all__ = [
    "DEFAULT_EMBEDDER",
    "BgeEmbedder",
    "ChunkKind",
    "CorpusChunk",
    "CorpusIndex",
    "Embedder",
    "Retriever",
    "SearchHit",
    "load_corpus",
]


class Retriever:
    """Embeds a query and returns the most relevant corpus chunks (decision D2).

    Loads the shipped corpus and prebuilt index for the default embedder, rebuilding on first use
    only as a fallback (non-default embedder or a corpus change).
    """

    def __init__(self, embedder: str = DEFAULT_EMBEDDER, *, top_k: int = 8):
        self.embedder = embedder
        self.top_k = top_k

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        """Return the corpus chunks that ground *query*, most relevant first."""
        raise NotImplementedError(
            "query-time retrieval is not wired yet — the scaffold pins the retriever surface; the "
            "corpus ingest, FAISS index, and loader are in place (load_corpus), and the retriever "
            "wiring is the next RAG step"
        )
