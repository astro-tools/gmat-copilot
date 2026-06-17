"""The build-time corpus extraction tool (decisions D2, D3) — maintainer-run, needs a GMAT install.

Ingests the GMAT help HTML (chunked per field-section), the stock sample scripts (per ``%----``
banner), the ``.gmf`` GmatFunctions, the gmat-script field catalogue (per type), and the first-party
domain-notes tier; embeds every chunk with the default embedder; and writes the chunked text, the
prebuilt FAISS index, and a manifest into the package. This is the step that *creates* the shipped
corpus — exactly the gmat-script ``fields-*.json`` pattern (reflected at build time so consumers
stay GMAT-free). It reads only static files and the GMAT-free gmat-script catalogue; it never needs
GMAT itself to run.

Run it from a checkout against a GMAT install::

    python -m gmat_copilot.rag.build --gmat-root /path/to/gmat-install

``sentence-transformers`` / ``faiss`` are base dependencies; the model downloads on first use.
"""

from __future__ import annotations

import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

from gmat_script import Catalog, load_catalog

from .embed import DEFAULT_EMBEDDER, BgeEmbedder, Embedder
from .loader import CORPUS_FILE, INDEX_FILE, MANIFEST_FILE, SHIPPED_CORPUS_DIR
from .schema import CorpusChunk, corpus_hash

__all__ = [
    "collect_chunks",
    "ingest_catalogue",
    "ingest_domain_notes",
    "ingest_gmf",
    "ingest_help",
    "ingest_samples",
    "write_corpus",
]

# Chunks shorter than this are extraction residue (nav crumbs, empty sections), not signal.
_MIN_CHARS = 40

# Default domain-notes source: the repo-root corpus/domain-notes/ (relative to this file).
_DEFAULT_NOTES_DIR = Path(__file__).resolve().parents[3] / "corpus" / "domain-notes"


class _HelpSections(HTMLParser):
    """Split a DocBook-generated GMAT help page into ``(heading, body)`` field-sections.

    GMAT help pages are nested ``<div class="refsection">`` blocks introduced by ``<h2>``/``<h3>``
    headings (Description, Fields, Remarks, Examples, ...). Per-page chunking is too coarse (V1), so
    text is flushed into a new chunk at each heading; navigation chrome is dropped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0  # inside <script>/<style>
        self._in_title = False
        self._div_depth = 0
        self._nav_depth: int | None = None  # div depth at which a nav block opened
        self._heading_tag: str | None = None  # currently capturing an <h2>/<h3> heading
        self.page_title = ""
        self._heading = ""  # heading text being captured
        self._section = ""  # heading of the section currently filling
        self._buf: list[str] = []
        self.sections: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "div":
            self._div_depth += 1
            cls = dict(attrs).get("class") or ""
            if self._nav_depth is None and cls in ("navheader", "navfooter"):
                self._nav_depth = self._div_depth
        elif tag == "title":
            self._in_title = True
        elif tag in ("h2", "h3"):
            self._flush()
            self._heading_tag = tag
            self._heading = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "div":
            if self._nav_depth is not None and self._div_depth == self._nav_depth:
                self._nav_depth = None
            self._div_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in ("h2", "h3") and self._heading_tag == tag:
            self._section = self._heading.strip()
            self._heading_tag = None

    def handle_data(self, data: str) -> None:
        if self._skip or self._nav_depth is not None:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.page_title += text
        elif self._heading_tag is not None:
            self._heading = f"{self._heading} {text}".strip()
        else:
            self._buf.append(text)

    def _flush(self) -> None:
        body = " ".join(self._buf).strip()
        self._buf = []
        if body:
            self.sections.append((self._section or "Description", body))
        self._section = ""

    def close(self) -> None:
        super().close()
        self._flush()


def ingest_help(help_dir: Path) -> list[CorpusChunk]:
    """One chunk per help field-section, each tagged with its resource/command page title (V1)."""
    chunks: list[CorpusChunk] = []
    for page in sorted(help_dir.glob("*.html")):
        parser = _HelpSections()
        parser.feed(page.read_text(encoding="utf-8", errors="ignore"))
        parser.close()
        title = parser.page_title.strip() or page.stem
        for heading, body in parser.sections:
            if len(body) < _MIN_CHARS:
                continue
            text = f"{title} — {heading}\n{body}"
            chunks.append(CorpusChunk(text=text, kind="help", origin=page.name, section=heading))
    return chunks


def ingest_samples(samples_dir: Path) -> list[CorpusChunk]:
    """One chunk per sample section, split on the ``%---------- <Name>`` banners."""
    chunks: list[CorpusChunk] = []
    for script in sorted(samples_dir.glob("*.script")):
        label = "header"
        buf: list[str] = []

        def flush(label: str, buf: list[str], name: str) -> None:
            body = "\n".join(buf).strip()
            if len(body) >= _MIN_CHARS:
                text = f"{name} — {label}\n{body}"
                chunks.append(CorpusChunk(text=text, kind="sample", origin=name, section=label))

        for line in script.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("%-"):
                name = stripped.strip("%- ")
                if name:  # a named banner starts a new section
                    flush(label, buf, script.name)
                    label = name
                    buf = []
                continue  # bare separator lines are dropped either way
            buf.append(line)
        flush(label, buf, script.name)
    return chunks


def ingest_gmf(gmat_root: Path) -> list[CorpusChunk]:
    """One chunk per ``.gmf`` GmatFunction file — the function-authoring idioms (V1)."""
    chunks: list[CorpusChunk] = []
    for gmf in sorted(gmat_root.rglob("*.gmf")):
        body = gmf.read_text(encoding="utf-8", errors="ignore").strip()
        if len(body) >= _MIN_CHARS:
            text = f"{gmf.stem} GmatFunction\n{body}"
            chunks.append(CorpusChunk(text=text, kind="gmf", origin=gmf.name, section=""))
    return chunks


def ingest_catalogue(catalog: Catalog) -> list[CorpusChunk]:
    """One structured chunk per catalogue type — the highest-precision vocabulary source (V1).

    Per-type keeps the index compact; per-field records are a later refinement (V1 forward note).
    """
    chunks: list[CorpusChunk] = []
    for type_name in sorted(catalog.types()):
        spec = catalog.type_spec(type_name)
        category = spec.category if spec is not None else ""
        kind_label = f"GMAT {category} type." if category else "GMAT type."
        lines = [f"{type_name} — {kind_label}"]
        field_lines: list[str] = []
        for field_name in catalog.fields(type_name):
            field = catalog.field(type_name, field_name)
            if field is None:
                continue
            parts = [field.type]
            if field.allowed:
                parts.append("allowed: " + ", ".join(field.allowed))
            if field.ref_target:
                parts.append(f"ref -> {field.ref_target}")
            if field.default not in (None, ""):
                parts.append(f"default {field.default}")
            if field.unit:
                parts.append(field.unit)
            if field.read_only:
                parts.append("read-only")
            field_lines.append(f"- {field_name} ({'; '.join(parts)})")
        if field_lines:
            lines.append("Fields:")
            lines.extend(field_lines)
        text = "\n".join(lines)
        if len(text) >= _MIN_CHARS:
            chunks.append(CorpusChunk(text=text, kind="catalogue", origin=type_name, section=""))
    return chunks


def ingest_domain_notes(notes_dir: Path) -> list[CorpusChunk]:
    """One chunk per domain-note topic file (first-party MIT modeling-semantics + gotchas, V1)."""
    chunks: list[CorpusChunk] = []
    if not notes_dir.is_dir():
        return chunks
    for note in sorted(notes_dir.glob("*.md")):
        body = note.read_text(encoding="utf-8").strip()
        if len(body) >= _MIN_CHARS:
            chunks.append(CorpusChunk(text=body, kind="domain-note", origin=note.name, section=""))
    return chunks


def collect_chunks(gmat_root: Path, *, notes_dir: Path, catalog: Catalog) -> list[CorpusChunk]:
    """Ingest every corpus tier into a single ordered chunk list (decision D2)."""
    help_dir = gmat_root / "docs" / "help" / "html"
    samples_dir = gmat_root / "samples"
    missing = [str(p) for p in (help_dir, samples_dir) if not p.is_dir()]
    if missing:
        raise FileNotFoundError(f"not found under the GMAT install: {', '.join(missing)}")
    return [
        *ingest_help(help_dir),
        *ingest_samples(samples_dir),
        *ingest_gmf(gmat_root),
        *ingest_catalogue(catalog),
        *ingest_domain_notes(notes_dir),
    ]


def write_corpus(
    chunks: list[CorpusChunk],
    *,
    out_dir: Path,
    embedder: Embedder,
    gmat_version: str,
) -> dict[str, object]:
    """Embed *chunks*, build the FAISS index, and write the text, index, and manifest to *out_dir*.

    Returns the manifest. A fixed corpus + embedder yields a byte-stable index, so the shipped index
    makes per-user retrieval deterministic (decision D2).
    """
    import faiss

    if not chunks:
        raise ValueError("refusing to write an empty corpus")

    vectors = embedder.encode([c.text for c in chunks])
    dim = int(vectors.shape[1])
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / CORPUS_FILE).open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    faiss.write_index(index, str(out_dir / INDEX_FILE))

    counts: dict[str, int] = {}
    for chunk in chunks:
        counts[chunk.kind] = counts.get(chunk.kind, 0) + 1
    manifest: dict[str, object] = {
        "embedder": embedder.name,
        "dim": dim,
        "n_chunks": len(chunks),
        "chunks_by_kind": counts,
        "gmat_version": gmat_version,
        "corpus_sha256": corpus_hash(tuple(chunks)),
    }
    (out_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract and embed the gmat-copilot RAG corpus.")
    ap.add_argument("--gmat-root", required=True, type=Path, help="GMAT install root.")
    ap.add_argument(
        "--notes-dir", type=Path, default=_DEFAULT_NOTES_DIR, help="domain-notes source directory."
    )
    ap.add_argument(
        "--out", type=Path, default=SHIPPED_CORPUS_DIR, help="output directory for the artifacts."
    )
    ap.add_argument("--embedder", default=DEFAULT_EMBEDDER, help="embedding model name.")
    args = ap.parse_args(argv)

    gmat_root = args.gmat_root.expanduser()
    if not gmat_root.is_dir():
        print(f"not a directory: {gmat_root}", file=sys.stderr)
        return 2

    catalog = load_catalog()
    chunks = collect_chunks(gmat_root, notes_dir=args.notes_dir.expanduser(), catalog=catalog)
    print(f"ingested {len(chunks)} chunks; embedding with {args.embedder} ...")
    manifest = write_corpus(
        chunks,
        out_dir=args.out.expanduser(),
        embedder=BgeEmbedder(args.embedder),
        gmat_version=catalog.gmat_version,
    )
    by_kind = json.dumps(manifest["chunks_by_kind"])
    print(f"wrote corpus to {args.out}: {by_kind}, dim {manifest['dim']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
