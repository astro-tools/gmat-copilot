"""V1 spike proof: GMAT RAG corpus ingest -> embed -> FAISS round-trip + size/time.

Reads a GMAT install's help HTML pages and sample ``.script`` files, chunks them,
embeds with a BGE-class sentence-transformer, builds a FAISS index, runs a few
natural-language retrieval queries as a sanity round-trip, and reports chunk
counts, build time, and on-disk sizes for both the FAISS index and the raw
chunk text.

It exists to settle two decisions for the design freeze (recorded as D2/D3):
the corpus composition, and whether the package ships a prebuilt index or ships
the chunked text and builds the index on first use. The GMAT corpus is
Apache-2.0 (the licence covers documentation source), so it is redistributable
with attribution; the size numbers below decide which redistribution form is
preferable.

Run::

    python v1_corpus_proof.py --gmat-root /path/to/gmat-install [--limit N]

or set ``GMAT_ROOT`` in the environment. ``--limit`` caps the number of files
ingested per source (for a quick smoke); omit it to measure the full corpus.

Dependencies: ``sentence-transformers`` and ``faiss-cpu``. These are NOT base
dependencies of the package -- install them in a throwaway environment to run
this spike.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

# A BGE-class embedding model: MIT-licensed, ~33M params, 384-dim. License-clean
# for either redistribution form (shipped index or shipped text + build-on-use).
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
# BGE retrieval convention: prefix the *query* (not the passages) with this.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class _TextExtractor(HTMLParser):
    """Collapse an HTML help page to its visible text."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


@dataclass
class Chunk:
    source: str  # basename of the source file
    kind: str  # "help" or "sample"
    section: str  # sample section banner label, or "" for help pages
    text: str


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def ingest_help(help_dir: Path, limit: int | None) -> list[Chunk]:
    """One chunk per help page (each page documents one resource/command/topic)."""
    chunks: list[Chunk] = []
    pages = sorted(help_dir.glob("*.html"))
    if limit is not None:
        pages = pages[:limit]
    for page in pages:
        text = html_to_text(page.read_text(encoding="utf-8", errors="ignore"))
        if len(text) >= 40:
            chunks.append(Chunk(source=page.name, kind="help", section="", text=text))
    return chunks


def ingest_samples(samples_dir: Path, limit: int | None) -> list[Chunk]:
    """One chunk per sample section, split on the ``%---------- <Name>`` banners."""
    chunks: list[Chunk] = []
    scripts = sorted(samples_dir.glob("*.script"))
    if limit is not None:
        scripts = scripts[:limit]
    for script in scripts:
        lines = script.read_text(encoding="utf-8", errors="ignore").splitlines()
        label = "header"
        buf: list[str] = []

        def flush() -> None:
            body = "\n".join(buf).strip()
            if len(body) >= 40:
                chunks.append(Chunk(source=script.name, kind="sample", section=label, text=body))

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("%-"):
                name = stripped.strip("%- ")
                if name:  # a named banner -> start a new section
                    flush()
                    label = name
                    buf = []
                # a bare separator line ("%-----...") is skipped either way
                continue
            buf.append(line)
        flush()
    return chunks


def resolve_corpus(gmat_root: Path) -> tuple[Path, Path]:
    help_dir = gmat_root / "docs" / "help" / "html"
    samples_dir = gmat_root / "samples"
    missing = [str(p) for p in (help_dir, samples_dir) if not p.is_dir()]
    if missing:
        sys.exit(f"not found under the GMAT install: {', '.join(missing)}")
    return help_dir, samples_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="V1 RAG-corpus proof (ingest -> embed -> FAISS).")
    ap.add_argument("--gmat-root", default=os.environ.get("GMAT_ROOT", ""),
                    help="GMAT install root (or set GMAT_ROOT).")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap files ingested per source (omit for the full corpus).")
    args = ap.parse_args()

    if not args.gmat_root:
        sys.exit("pass --gmat-root /path/to/gmat-install or set GMAT_ROOT")
    gmat_root = Path(args.gmat_root).expanduser()
    if not gmat_root.is_dir():
        sys.exit(f"not a directory: {gmat_root}")

    help_dir, samples_dir = resolve_corpus(gmat_root)
    chunks = ingest_help(help_dir, args.limit) + ingest_samples(samples_dir, args.limit)
    n_help = sum(c.kind == "help" for c in chunks)
    n_sample = sum(c.kind == "sample" for c in chunks)
    print(f"ingested {len(chunks)} chunks  ({n_help} help-page, {n_sample} sample-section)")
    if not chunks:
        sys.exit("no chunks ingested")

    # Heavy imports deferred so --help stays instant without the ML stack installed.
    import faiss  # type: ignore[import-not-found]
    import numpy as np
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

    print(f"loading embedding model {EMBED_MODEL} ...")
    model = SentenceTransformer(EMBED_MODEL)

    texts = [c.text for c in chunks]
    t0 = time.perf_counter()
    emb = np.asarray(
        model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False),
        dtype="float32",
    )
    t_embed = time.perf_counter() - t0
    dim = int(emb.shape[1])

    t0 = time.perf_counter()
    index = faiss.IndexFlatIP(dim)
    index.add(emb)
    t_index = time.perf_counter() - t0

    with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as fh:
        faiss.write_index(index, fh.name)
        index_bytes = os.path.getsize(fh.name)
    os.unlink(fh.name)

    payload = [{"source": c.source, "kind": c.kind, "section": c.section, "text": c.text}
               for c in chunks]
    text_bytes = len(json.dumps(payload).encode("utf-8"))

    # Sanity round-trip: a few NL queries should retrieve topically-correct chunks.
    queries = [
        "set a spacecraft's semi-major axis and eccentricity",
        "apply an impulsive maneuver delta-v in the VNB frame",
        "propagate the orbit until apoapsis",
    ]
    qemb = np.asarray(
        model.encode([BGE_QUERY_PREFIX + q for q in queries], normalize_embeddings=True),
        dtype="float32",
    )
    scores, idxs = index.search(qemb, 3)

    print()
    print("=== round-trip retrieval (top-3 per query) ===")
    for q, row, srow in zip(queries, idxs, scores):
        print(f"\nQ: {q}")
        for rank, (i, s) in enumerate(zip(row, srow), 1):
            c = chunks[int(i)]
            tag = c.source if c.kind == "help" else f"{c.source}:{c.section}"
            print(f"  {rank}. [{s:.3f}] {c.kind:6} {tag}")

    mb = 1024 * 1024
    print()
    print("=== measurements ===")
    print(f"chunks              : {len(chunks)}")
    print(f"embedding dim       : {dim}")
    print(f"embed time          : {t_embed:6.2f} s  ({1000 * t_embed / len(chunks):.1f} ms/chunk)")
    print(f"index build time    : {t_index:6.3f} s")
    print(f"FAISS index size    : {index_bytes / mb:6.2f} MiB  (flat float32)")
    print(f"raw chunk-text size : {text_bytes / mb:6.2f} MiB  (json, uncompressed)")
    if args.limit is not None:
        print("(subsampled via --limit; omit it to measure the full corpus)")


if __name__ == "__main__":
    main()
