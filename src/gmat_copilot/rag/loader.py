"""The runtime corpus loader (decision D2) — GMAT-free, no network on the default path.

Loads the chunked text and the prebuilt FAISS index shipped in the package. For the default embedder
that is a pure file load: no GMAT install, no model download, no rebuild. A non-default embedder (or
a changed corpus) falls back to re-embedding the shipped text and caching the rebuilt index under an
XDG cache directory, keyed by embedder and corpus hash so it is reused across runs and invalidated
when either changes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .embed import Embedder
from .schema import CorpusChunk, corpus_hash

__all__ = [
    "CORPUS_FILE",
    "INDEX_FILE",
    "MANIFEST_FILE",
    "SHIPPED_CORPUS_DIR",
    "CorpusIndex",
    "SearchHit",
    "load_corpus",
]

CORPUS_FILE = "corpus.jsonl"
INDEX_FILE = "index.faiss"
MANIFEST_FILE = "manifest.json"

# The corpus artifacts ship as package data alongside this module.
SHIPPED_CORPUS_DIR = Path(__file__).parent / "corpus"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A retrieved corpus chunk and its similarity score (higher is closer)."""

    chunk: CorpusChunk
    score: float


class CorpusIndex:
    """The loaded corpus: the chunks, the FAISS index, and the embedder they were built for."""

    def __init__(
        self, chunks: tuple[CorpusChunk, ...], index: Any, *, embedder_name: str, dim: int
    ) -> None:
        self._chunks = chunks
        self._index = index
        self.embedder_name = embedder_name
        self.dim = dim

    @property
    def chunks(self) -> tuple[CorpusChunk, ...]:
        return self._chunks

    def __len__(self) -> int:
        return len(self._chunks)

    def search(self, query: str, *, embedder: Embedder, k: int = 8) -> list[SearchHit]:
        """Embed *query* and return the *k* most similar chunks, most relevant first.

        *embedder* must be the one the index was built for (the same model that loaded or rebuilt
        it), so the query lands in the same vector space.
        """
        if not self._chunks:
            return []
        vectors = embedder.encode([query], is_query=True)
        scores, indices = self._index.search(vectors, min(k, len(self._chunks)))
        hits: list[SearchHit] = []
        for idx, score in zip(indices[0], scores[0], strict=True):
            if int(idx) < 0:
                continue
            hits.append(SearchHit(chunk=self._chunks[int(idx)], score=float(score)))
        return hits


def load_corpus(embedder: Embedder | None = None, *, corpus_dir: Path | None = None) -> CorpusIndex:
    """Load the shipped corpus and its index (decision D2).

    :param embedder: the embedder retrieval will use. ``None`` selects the default the index was
        built for, so the prebuilt index is loaded directly. A non-default embedder triggers a
        one-time fallback rebuild, cached under the XDG cache directory.
    :param corpus_dir: the corpus directory; defaults to the shipped package data.
    """
    import faiss

    corpus_dir = corpus_dir or SHIPPED_CORPUS_DIR
    chunks = _read_chunks(corpus_dir / CORPUS_FILE)
    manifest = json.loads((corpus_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    shipped_embedder = str(manifest["embedder"])

    if embedder is None or embedder.name == shipped_embedder:
        # Default path: load the prebuilt index — no model, no rebuild, deterministic for everyone.
        index = faiss.read_index(str(corpus_dir / INDEX_FILE))
        return CorpusIndex(chunks, index, embedder_name=shipped_embedder, dim=int(manifest["dim"]))

    # Fallback: a non-default embedder needs its own index. Rebuild once and cache it.
    return _rebuild(chunks, embedder)


def _rebuild(chunks: tuple[CorpusChunk, ...], embedder: Embedder) -> CorpusIndex:
    import faiss

    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    key = f"{_slug(embedder.name)}-{corpus_hash(chunks)[:16]}"
    cached = cache / f"{key}.{INDEX_FILE}"
    if cached.exists():
        index = faiss.read_index(str(cached))
        return CorpusIndex(chunks, index, embedder_name=embedder.name, dim=int(index.d))

    vectors = embedder.encode([c.text for c in chunks])
    dim = int(vectors.shape[1])
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)
    faiss.write_index(index, str(cached))
    return CorpusIndex(chunks, index, embedder_name=embedder.name, dim=dim)


def _read_chunks(path: Path) -> tuple[CorpusChunk, ...]:
    with path.open(encoding="utf-8") as fh:
        return tuple(CorpusChunk.from_dict(json.loads(line)) for line in fh if line.strip())


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "gmat-copilot" / "rag"


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
