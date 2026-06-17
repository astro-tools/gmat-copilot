# Corpus & licences

Generation is *retrieval-grounded*: a request is answered against relevant passages from a curated
GMAT corpus, so the model writes against real syntax rather than from memory. The corpus and a
prebuilt index ship with the package, so **you never need a GMAT install to generate**.

## What's in it

The corpus has five tiers. Four are extracted from a GMAT R2026a distribution; one is first-party.

| Tier | Source | Chunks |
| --- | --- | --- |
| `help` | GMAT help documentation (reference, tutorials, how-to and chapter pages) | 1427 |
| `sample` | the stock sample mission scripts | 586 |
| `catalogue` | the resource/command field catalogue (types, fields, enums) | 102 |
| `domain-note` | hand-written modeling-semantics and gotcha notes | 20 |
| `gmf` | the sample GmatFunction (`.gmf`) files | 9 |

That is **2144 chunks** in total. Each chunk records its tier and origin, so a result's
[retrieval trace](output-schema.md) attributes every grounding passage back to a help page, a
sample-script section, a GmatFunction, a catalogue type, or a domain note.

The User's Guide PDF (the same source as the help HTML), internal spec PDFs, and Python-API notes
are deliberately excluded.

## Ship vs. rebuild

Maintainers extract the chunked corpus text at build time and the package ships both the text
(`corpus.jsonl`) and a **prebuilt FAISS index** (`index.faiss`) for the default embedder,
`BAAI/bge-small-en-v1.5` (384-dimensional). At runtime the index loads directly — no GMAT, no
network. The index is rebuilt on first use **only as a fallback**, when you supply a non-default
embedder or the corpus has changed; a content hash in the manifest keys that fallback cache so a
stale rebuild is invalidated automatically. Shipping the prebuilt index also makes retrieval
deterministic, which the evaluation suite relies on.

## Licences

Redistribution is the load-bearing question for any GMAT-derived corpus, and it is clean:

- **GMAT-derived tiers** (`help`, `sample`, `catalogue`, `gmf`) come from GMAT, which NASA's Goddard
  Space Flight Center distributes under the **Apache License 2.0**. That licence explicitly covers
  documentation source and permits redistribution with attribution. The attribution ships in
  [`THIRD-PARTY-NOTICES`](https://github.com/astro-tools/gmat-copilot/blob/main/THIRD-PARTY-NOTICES)
  alongside the project's MIT `LICENSE`. Only derived text and embeddings are redistributed — no
  GMAT source code or binaries.
- **The `domain-note` tier** is original first-party content authored for this project, covered by
  the project's **MIT** licence.
- **The embedding model**, `BAAI/bge-small-en-v1.5`, is **MIT**-licensed. The model itself is not
  redistributed; only the embeddings it produced for the corpus are.

Apache-2.0 content is one-way compatible inside an MIT project given attribution, so the whole corpus
redistributes without a contractual block.
