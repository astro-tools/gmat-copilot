"""Corpus ingest, the FAISS index, and the retriever (decisions D2, D3).

Retrieval grounds generation in the GMAT help pages, the stock sample scripts, the GmatFunctions,
the gmat-script field catalogue, and a curated domain-notes tier. The corpus text and a prebuilt
index for the default embedder are extracted by maintainers at build time and shipped with the
package, so users never need a GMAT install to generate. ``sentence-transformers`` / ``faiss`` are
imported lazily inside the retriever so importing the package stays light.
"""

from __future__ import annotations

from ..result import RetrievalTrace

__all__ = ["Retriever"]

DEFAULT_EMBEDDER = "BAAI/bge-small-en-v1.5"


class Retriever:
    """Embeds a query and returns the most relevant corpus chunks (decision D2).

    Ships with a prebuilt index for the default embedder and rebuilds on first use only as a
    fallback (non-default embedder or a corpus change).
    """

    def __init__(self, embedder: str = DEFAULT_EMBEDDER, *, top_k: int = 8):
        self.embedder = embedder
        self.top_k = top_k

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        """Return the corpus chunks that ground *query*, most relevant first."""
        raise NotImplementedError(
            "retrieval is not wired yet — the scaffold pins the retriever surface; the corpus "
            "extraction and FAISS index are added by the RAG feature work"
        )
