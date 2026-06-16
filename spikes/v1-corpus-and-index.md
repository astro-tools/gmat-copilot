# V1 — RAG corpus composition, licensing & ship-vs-build

**Spike question.** Decide what the retrieval corpus contains, confirm each source is
redistributable (or must be built on the user's machine), and choose whether the embedded
index ships prebuilt or is built on first use. Outcome feeds the design freeze as **D2**
(corpus composition + index ship-vs-build) and **D3** (corpus source licences).

## Recommendation (TL;DR)

- **Corpus (D2):** the GMAT **help HTML** (reference *and* the tutorial / how-to / chapter
  pages) + the **sample scripts** + the **`.gmf` GmatFunction** files + the **gmat-script
  catalogue** + a hand-written **domain-notes** tier (modeling semantics and gotchas). The
  User's Guide PDF and the internal spec PDFs are excluded as redundant / out-of-scope; the
  gmat-python notes are excluded (wrong surface — Python API).
- **Licensing (D3):** the GMAT corpus is **Apache-2.0** (the licence covers documentation
  source) → redistributable with attribution; the domain notes are first-party (MIT); the
  embedding model is MIT. No contractual block.
- **Ship-vs-build (D2):** the **maintainers extract the corpus at build time** so consumers
  never need GMAT (the gmat-script `fields-*.json` pattern). **Ship both the chunked text and a
  prebuilt index**; rebuild the index on first use only as a **fallback** (non-default embedder
  or corpus change). GMAT-free for the user either way.

## Licensing (D3)

- `License.txt` in the R2026a install is the **Apache License 2.0**. Apache-2.0 §1 defines
  "Source" form as including "documentation source", so the **sample scripts**, the **help
  HTML**, and the **User's Guide** are all covered by it.
- Apache-2.0 permits redistribution of the material (and derived representations such as
  embeddings) provided we **retain the licence text and attribution/NOTICE and state
  changes**. The sample files carry only a description comment header (no per-file licence),
  so they inherit the install licence.
- The **domain-notes** tier is first-party content (authored for the project, seeded from the
  workspace's gmat skills), shipped under the project's **MIT** licence — no third-party
  entanglement.
- The org ships its own code under **MIT**. MIT code bundling **Apache-2.0** third-party
  content is compatible one-way: ship a `THIRD-PARTY-NOTICES` carrying GMAT's Apache-2.0
  attribution alongside the project's MIT `LICENSE`. (The design freeze / scaffold lands the
  notices file; this spike only fixes the requirement.)
- Embedding model **`BAAI/bge-small-en-v1.5`** is **MIT** — clean for either redistribution
  form.

## Corpus composition (D2)

Reference pages + samples + catalogue cover **vocabulary, syntax, and worked examples**. They
do *not* cover the **modeling-semantics + gotcha** layer — "how to model intent X" and the
common mistakes — which is the layer an ungrounded model gets wrong. The domain-notes tier and
the help tutorials fill it.

Tier 1 (v0.1):

- **`docs/help/html/*.html`** — 249 usable pages: the resource/command **reference** pages
  *and* the **tutorial / how-to / chapter** pages (`SimulatingAnOrbit`, `SimpleOrbitTransfer`,
  `Mars_B_Plane_Targeting`, the `Tut_*` set, 65 `ch*` chapters). The tutorials are the GMAT-side
  intent→script bridge and are already part of this source. Chunk **per field-section**, not
  per-page (per-page is too coarse — see Forward notes).
- **`samples/*.script`** — 88 files, split on the `%---------- <Name>` section banners (586
  section chunks). The working idioms — how a real, runnable script is shaped.
- **`samples/userfunctions/*.gmf`** — 9 GmatFunction files: function-authoring idioms (inputs /
  outputs / `Global`), the one script form the `.script` samples don't show.
- **gmat-script catalogue** (`load_catalog()`) — structured type/field/enum/default data
  (102 types, 2614 fields), GMAT-free; embedded as per-type / per-field records. The help
  field-table **descriptions** (units, allowed values) ship alongside it as prose — the
  catalogue gives the *shape*, the help text gives the *meaning*.
- **Domain notes** (hand-written) — distilled modeling semantics and gotchas: the intent→
  construct mapping and the pitfalls the linter catches (literal-only Initialization, the
  body-vs-CoordinateSystem dependency on parameters, hardware-fields-not-reportable, the
  logical-operator rules). Seeded from the workspace's **gmat-script** and
  **gmat-orbital-mechanics** skill references (and the conceptual parts of **gmat-general** —
  mission planning, the resource/command catalogues). Adapted into the repo as
  `corpus/domain-notes/` (MIT), *not* read in place from the skills.

Excluded (to keep the corpus high-signal):

- **`docs/GMAT_UsersGuide.pdf`** — the same DocBook source as the help HTML, just monolithic
  (1299 pages) with extraction noise; its tutorials are already in the help HTML. Adds bulk,
  not coverage.
- **The internal spec PDFs** (`GMATMathSpec`, `GMAT-Architectural-Specification`,
  `GMATEstimationSpecification`, `GMAT_OptimalControl_Specification`, `GMAT_V&V_*`, …) —
  low-level / internal, not about authoring scripts.
- **gmat-python skill notes** — the `gmatpy` Python API; folding them in would pollute the
  `.script` corpus with Python idioms and risk the model emitting Python where it should emit a
  script.
- **Generic astrodynamics theory** — the model already has it; numeric computation is
  astrodynamics-mcp's job, not the corpus's. Only the GMAT-contextual semantics earn a place.

A note on size: the corpus is small, and that is fine for RAG — retrieval precision depends on
covering the right *dimensions* (vocabulary, idioms, semantics, gotchas), not raw byte count. A
tight, well-chunked, high-signal corpus beats a large noisy one; the User's Guide PDF would add
bulk and noise, not coverage.

## Ship-vs-build (D2)

Separate three artifacts; the user must never need the first:

| Artifact | From | Needs a GMAT install? |
|---|---|---|
| (a) raw sources (help HTML, samples, catalogue) | a GMAT install | yes |
| (b) chunked corpus **text** (extracted + cleaned from a) | derived from (a) | yes, to *create* it |
| (c) FAISS **index** (embeddings of b) | the embedding model | no — only the embedder |

Decision:

- **(b) is extracted by the maintainers at build time** from a GMAT install and shipped in the
  package — exactly the gmat-script pattern (it ships `fields-R2026a.json`, reflected from GMAT
  at build time, so its consumers are GMAT-free). Apache-2.0 permits the redistribution.
  **The user therefore never needs a GMAT install or its discovery.**
- **Ship both (b) the text and (c) a prebuilt index** (for the default embedder). Both are tiny
  — 2.6 MiB text + 1.2 MiB index ≈ 3.8 MiB.
- **Rebuild the index on first use only as a fallback** — when the user overrides the default
  embedder, or the shipped corpus/catalogue changes. Rebuilding needs the embedding model
  (~130 MiB, downloaded), **not** GMAT.

Why ship the prebuilt index, not just the text:

- **Reproducibility.** v0.1's correctness surface is a *deterministic* eval / leaderboard. A
  rebuilt index can vary at the margins (BLAS / architecture / library float differences flipping
  near-tied retrievals); a shipped index is byte-identical for everyone.
- **Instant first query.** The ~5 s embed becomes the fallback-only cost.
- **Negligible cost.** 1.2 MiB; and the embedder must download anyway for query-time embedding,
  so a prebuilt index adds no *new* dependency.

Ship-some / build-some by source (v0.2 refinement): help + samples ship as frozen text, but the
**catalogue** slice can be regenerated from the installed **gmat-script** dependency at
index-build time, so it tracks the gmat-script version and never goes stale. v0.1 keeps it
simple — ship all of (b) frozen plus the prebuilt index; adopt the catalogue regeneration later.

## Proof

Script: [`v1_corpus_proof.py`](./v1_corpus_proof.py) — ingest → chunk → embed → FAISS →
round-trip → measure. Portable (corpus via `--gmat-root` / `GMAT_ROOT`); deps
`sentence-transformers` + `faiss-cpu` (not base deps — install in a throwaway env). The build
cost it measures is the **fallback** path (the maintainers' build-time index is the default).

```
python spikes/v1_corpus_proof.py --gmat-root <gmat-install>
```

Full-corpus run on the help-pages + samples slice (R2026a, `BAAI/bge-small-en-v1.5`, CPU):

| metric | value |
|---|---|
| chunks | 835 (249 help-page, 586 sample-section) |
| embedding dimension | 384 |
| embed time | 4.74 s (5.7 ms/chunk) |
| index build time | 0.001 s |
| FAISS index size | **1.22 MiB** (flat float32) |
| raw chunk-text size | **2.61 MiB** (json, uncompressed) |

(The `.gmf`, catalogue, and domain-notes additions add little volume — a handful of small files
and structured records — so the numbers above bound the order of magnitude.)

Round-trip sanity (3 NL queries, top hit shown) — retrieval is topically correct:

- *"apply an impulsive maneuver delta-v in the VNB frame"* → `ImpulsiveBurn.html` (0.754)
- *"propagate the orbit until apoapsis"* → `SimulatingAnOrbit.html` (0.771)
- *"set a spacecraft's semi-major axis and eccentricity"* → a Keplerian sample +
  `SpacecraftVisualizationProperties.html` (see Forward notes on granularity)

Embeddings are deterministic for a pinned model, so the index rebuilds identically run-to-run.

## Forward notes (for the RAG ingest + retriever work)

- **Finer help chunking.** Per-page help chunks are coarse — the semi-major-axis query's top hit
  was the visualization-properties page rather than the orbit-state page. Split help pages per
  field/section.
- **Catalogue as structured records,** the highest-precision vocabulary source; consider
  regenerating it from the gmat-script dependency at build time (the by-source split above).
- **Domain notes** seed from the gmat-script + gmat-orbital-mechanics (+ gmat-general) skill
  references; adapt into `corpus/domain-notes/` (MIT), don't couple to the workspace skills.
- **Prebuilt index** is a release-time build artifact (re-generate and re-ship when the corpus
  or default embedder changes), like any compiled artifact.
- **Attribution.** Ship `THIRD-PARTY-NOTICES` with GMAT's Apache-2.0 attribution; landed by the
  scaffold / design freeze.
- **BGE convention.** Prefix queries (not passages) with the BGE retrieval instruction, as the
  proof does.
