"""Query-time retrieval — the retrieval half of decision D2.

Embeds a natural-language intent with the same model the index was built for, runs a top-k search
over the shipped FAISS index (loaded by :func:`.load_corpus`), and returns a
:class:`~gmat_copilot.result.RetrievalTrace` of the chunks that ground the request, each tagged with
a source label for attribution. A configurable token budget bounds how much context is kept, so the
trace is exactly what an assembled context block contains. Retrieval is deterministic for a fixed
index and query.
"""

from __future__ import annotations

from pathlib import Path

from ..result import RetrievalChunk, RetrievalTrace
from .embed import DEFAULT_EMBEDDER, BgeEmbedder, Embedder
from .loader import CorpusIndex, SearchHit, load_corpus
from .schema import CorpusChunk

__all__ = ["DEFAULT_TOKEN_BUDGET", "Retriever", "assemble_context"]

# A default bound on the grounding context. Token counts are estimated dependency-free (~4 chars per
# token), which is approximate but enough to keep the context block bounded.
DEFAULT_TOKEN_BUDGET = 2048

# Human-readable attribution prefixes per corpus tier (decision D3: GMAT-derived vs first-party).
_SOURCE_PREFIX = {
    "help": "GMAT help",
    "sample": "GMAT sample",
    "gmf": "GMAT function",
    "catalogue": "GMAT catalogue",
    "domain-note": "Domain note",
}


def _estimate_tokens(text: str) -> int:
    """Approximate token count (~4 characters per token); never returns zero."""
    return max(1, len(text) // 4)


def _source_label(chunk: CorpusChunk) -> str:
    """A readable source attribution, e.g. ``GMAT help: ImpulsiveBurn.html — Fields``."""
    prefix = _SOURCE_PREFIX.get(chunk.kind, chunk.kind)
    label = f"{prefix}: {chunk.origin}"
    if chunk.section:
        label += f" — {chunk.section}"
    return label


class Retriever:
    """Embeds a query and returns the most relevant corpus chunks (decision D2).

    Loads the shipped corpus and prebuilt index for the default embedder (rebuilding on first use
    only as a fallback for a non-default embedder or a corpus change), then runs a top-k search and
    trims the result to a token budget. The corpus and model load lazily on the first
    :meth:`retrieve`, so constructing a ``Retriever`` is cheap.
    """

    def __init__(
        self,
        embedder: str | Embedder = DEFAULT_EMBEDDER,
        *,
        top_k: int = 8,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        corpus_dir: Path | None = None,
    ) -> None:
        self._embedder: Embedder | None = None if isinstance(embedder, str) else embedder
        self._embedder_name = embedder if isinstance(embedder, str) else embedder.name
        self.top_k = top_k
        self.token_budget = token_budget
        self._corpus_dir = corpus_dir
        self._index: CorpusIndex | None = None

    def _ensure(self) -> tuple[CorpusIndex, Embedder]:
        if self._embedder is None:
            self._embedder = BgeEmbedder(self._embedder_name)
        if self._index is None:
            self._index = load_corpus(self._embedder, corpus_dir=self._corpus_dir)
        return self._index, self._embedder

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        """Return the corpus chunks that ground *query*, most relevant first.

        Trims the ranked hits to :attr:`token_budget`, keeping whole chunks in rank order and always
        retaining at least the top hit. The returned trace is exactly the set
        :func:`assemble_context` formats into the grounding block.
        """
        index, embedder = self._ensure()
        hits = index.search(query, embedder=embedder, k=top_k if top_k is not None else self.top_k)

        kept: list[SearchHit] = []
        used = 0
        for hit in hits:
            cost = _estimate_tokens(hit.chunk.text)
            if kept and used + cost > self.token_budget:
                break
            kept.append(hit)
            used += cost

        chunks = tuple(
            RetrievalChunk(source=_source_label(hit.chunk), score=hit.score, text=hit.chunk.text)
            for hit in kept
        )
        return RetrievalTrace(chunks=chunks)


def assemble_context(trace: RetrievalTrace) -> str:
    """Format a retrieval trace into a bounded, source-attributed grounding block.

    Each chunk is rendered under its source label so generation (and a reader of the result) can see
    where the grounding came from. Empty when the trace has no chunks.
    """
    return "\n\n".join(f"[{chunk.source}]\n{chunk.text}" for chunk in trace.chunks)
