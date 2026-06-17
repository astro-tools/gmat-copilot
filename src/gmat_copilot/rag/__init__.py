"""Corpus ingest, the FAISS index, and the retriever (decisions D2, D3).

Retrieval grounds generation in the GMAT help pages, the stock sample scripts, the GmatFunctions,
the gmat-script field catalogue, and a curated domain-notes tier. The corpus text and a prebuilt
index for the default embedder are extracted by maintainers at build time (:mod:`.build`) and
shipped with the package; the runtime :func:`.load_corpus` loads them with no GMAT install and no
network, rebuilding the index on first use only as a fallback. ``sentence-transformers`` / ``faiss``
are imported lazily so importing the package stays light.
"""

from __future__ import annotations

from .embed import DEFAULT_EMBEDDER, BgeEmbedder, Embedder
from .loader import CorpusIndex, SearchHit, load_corpus
from .retriever import DEFAULT_TOKEN_BUDGET, Retriever, assemble_context
from .schema import ChunkKind, CorpusChunk

__all__ = [
    "DEFAULT_EMBEDDER",
    "DEFAULT_TOKEN_BUDGET",
    "BgeEmbedder",
    "ChunkKind",
    "CorpusChunk",
    "CorpusIndex",
    "Embedder",
    "Retriever",
    "SearchHit",
    "assemble_context",
    "load_corpus",
]
