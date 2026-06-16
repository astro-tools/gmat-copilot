# V1 — RAG corpus composition, licensing & ship-vs-build

**Spike question.** Decide what the retrieval corpus contains, confirm each source is
redistributable (or must be built on the user's machine), and choose whether the embedded
index ships prebuilt or is built on first use. Outcome feeds the design freeze as **D2**
(corpus composition + index ship-vs-build) and **D3** (corpus source licences).

## Recommendation (TL;DR)

- **Corpus (D2):** the GMAT **help HTML pages** + the **sample scripts** + the **gmat-script
  catalogue** (structured types/fields/enums). The User's Guide PDF is a deferred second tier.
- **Licensing (D3):** the GMAT corpus is **Apache-2.0** (the licence covers documentation
  source), so it is **redistributable with attribution**; the embedding model is MIT. The
  load-bearing redistribution risk resolves positively — there is no contractual block.
- **Ship-vs-build (D2):** **ship the chunked corpus text** in the package and **build the
  FAISS index on first use**, cached under an XDG dir. The whole corpus is tiny (1.2 MiB index,
  2.6 MiB text) and rebuilds in ~5 s; because the embedding model must be present at query time
  anyway, shipping a prebuilt index would save only the build step while locking the index to a
  fixed model + dimension. Shipping text keeps the base install **GMAT-free** and lets the index
  rebuild deterministically against whatever embedder is pinned.

## Licensing (D3)

- `License.txt` in the R2026a install is the **Apache License 2.0**. Apache-2.0 §1 defines
  "Source" form as including "documentation source", so the **sample scripts**, the **help
  HTML**, and the **User's Guide** are all covered by it.
- Apache-2.0 permits redistribution of the material (and derived representations such as
  embeddings) provided we **retain the licence text and attribution/NOTICE and state
  changes**. The sample files carry only a description comment header (no per-file licence),
  so they inherit the install licence.
- The org ships its own code under **MIT**. MIT code bundling **Apache-2.0** third-party
  content is compatible one-way: ship a `THIRD-PARTY-NOTICES` carrying GMAT's Apache-2.0
  attribution alongside the project's MIT `LICENSE`. (The design freeze / scaffold lands the
  notices file; this spike only fixes the requirement.)
- Embedding model **`BAAI/bge-small-en-v1.5`** is **MIT** — clean for either redistribution
  form.

## Corpus composition (D2)

Tier 1 (v0.1):

- **`docs/help/html/*.html`** — 250 pages (249 usable after a minimum-length filter), one per
  resource / command / topic. The cleanest structured prose; the resource and field vocabulary
  lives here.
- **`samples/*.script`** — 88 files, split on the `%---------- <Name>` section banners into
  586 section chunks. The working idioms — how a real, runnable script is actually shaped.
- **gmat-script catalogue** (`load_catalog()`) — the structured type/field/enum/default data
  (102 types, 2614 fields), already GMAT-free. The exact vocabulary as data, highest precision.
  Not embedded in this proof (kept dependency-light), but a first-class Tier-1 source for the
  real ingest layer, embedded as per-type / per-field records.

Tier 2 (deferred):

- **`docs/GMAT_UsersGuide.pdf`** — broad conceptual prose, but PDF extraction is noisier and
  heavier than the HTML help. Revisit only if help + samples coverage proves insufficient.

Chunk granularity: help = per-page to start (per-field-section is the obvious refinement — see
Forward notes); sample = per-section banner block; catalogue = per-type / per-field record.

## Ship-vs-build (D2)

**Ship chunked text; build the FAISS index on first use; cache under XDG.** Rationale, grounded
in the proof numbers below:

- The corpus is small — full chunk text is 2.6 MiB (compresses well), the full flat float32
  index is 1.2 MiB.
- Building is cheap — ~5 s on CPU to embed all 835 chunks; the FAISS build itself is ~1 ms.
- The embedding model must be loaded at **query** time to embed the user's request, so its
  one-time ~130 MiB download is unavoidable regardless of ship-vs-build. A prebuilt index would
  therefore save only the ~5 s build, at the cost of locking the index to one model + dimension.
- Shipping text keeps the base install GMAT-free (no GMAT needed to build the index) and lets
  the index rebuild deterministically when the embedder is bumped.

A prebuilt index can still be shipped later as an optional fast-path; it is not needed for v0.1.

## Proof

Script: [`v1_corpus_proof.py`](./v1_corpus_proof.py) — ingest → chunk → embed → FAISS →
round-trip → measure. Portable (corpus via `--gmat-root` / `GMAT_ROOT`); deps
`sentence-transformers` + `faiss-cpu` (not base deps — install in a throwaway env).

```
python spikes/v1_corpus_proof.py --gmat-root <gmat-install>
```

Full-corpus run (R2026a, `BAAI/bge-small-en-v1.5`, CPU):

| metric | value |
|---|---|
| chunks | 835 (249 help-page, 586 sample-section) |
| embedding dimension | 384 |
| embed time | 4.74 s (5.7 ms/chunk) |
| index build time | 0.001 s |
| FAISS index size | **1.22 MiB** (flat float32) |
| raw chunk-text size | **2.61 MiB** (json, uncompressed) |

Round-trip sanity (3 NL queries, top hit shown) — retrieval is topically correct:

- *"apply an impulsive maneuver delta-v in the VNB frame"* → `ImpulsiveBurn.html` (0.754)
- *"propagate the orbit until apoapsis"* → `SimulatingAnOrbit.html` (0.771)
- *"set a spacecraft's semi-major axis and eccentricity"* → a Keplerian sample +
  `SpacecraftVisualizationProperties.html` (see Forward notes on granularity)

Embeddings are deterministic for a pinned model, so the index rebuilds identically run-to-run.

## Forward notes (for the RAG ingest + retriever work)

- **Chunk granularity.** Per-page help chunks are coarse — the semi-major-axis query's top hit
  was the visualization-properties page rather than the orbit-state page. Splitting help pages
  per field/section will sharpen retrieval; the retriever should tune this.
- **Catalogue as structured records.** Embed the gmat-script catalogue as per-type/per-field
  records — the highest-precision vocabulary source, and the anti-hallucination lever.
- **Attribution.** Ship `THIRD-PARTY-NOTICES` with GMAT's Apache-2.0 attribution; landed by the
  scaffold / design freeze.
- **BGE convention.** Prefix queries (not passages) with the BGE retrieval instruction, as the
  proof does.
