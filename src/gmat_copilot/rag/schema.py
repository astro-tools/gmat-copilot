"""The corpus chunk schema — one embedded passage plus its provenance (decisions D2, D3).

Every chunk records where it came from so the retrieval trace can attribute grounding back to a
GMAT help page, a sample-script section, a GmatFunction, a catalogue type, or a domain note. The
``kind`` also fixes the licence tier: everything extracted from a GMAT install is Apache-2.0
(carried in ``THIRD-PARTY-NOTICES``); the ``domain-note`` tier is first-party MIT.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, cast

__all__ = ["ChunkKind", "CorpusChunk", "corpus_hash"]

# The five corpus tiers (decision D2). "help"/"sample"/"gmf"/"catalogue" are GMAT-derived
# (Apache-2.0); "domain-note" is first-party (MIT).
ChunkKind = Literal["help", "sample", "gmf", "catalogue", "domain-note"]


@dataclass(frozen=True, slots=True)
class CorpusChunk:
    """One retrieval passage with its source provenance.

    :param text: the passage embedded and returned as grounding.
    :param kind: the corpus tier the passage belongs to.
    :param origin: the source identifier — a help-page name, sample/GmatFunction file name,
        catalogue type name, or domain-note name.
    :param section: a finer locator within the origin — a help field-section heading or a sample
        ``%----`` banner label; empty for whole-file tiers.
    """

    text: str
    kind: ChunkKind
    origin: str
    section: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "kind": self.kind,
            "origin": self.origin,
            "section": self.section,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> CorpusChunk:
        return cls(
            text=data["text"],
            kind=cast(ChunkKind, data["kind"]),
            origin=data["origin"],
            section=data.get("section", ""),
        )


def corpus_hash(chunks: tuple[CorpusChunk, ...]) -> str:
    """A content hash of an ordered chunk sequence.

    The index rows align with chunk order, so the hash covers both content and order. Build records
    it in the manifest; the loader recomputes it to key the fallback-rebuild cache, so a corpus
    change invalidates a stale cached index (decision D2).
    """
    payload = json.dumps([c.to_dict() for c in chunks], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
