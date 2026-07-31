# BGE-M3 Embedding Profile

KnowledgeNexus uses **BAAI/bge-m3** for embeddings.

## Dense configuration (locked)

- Vector dimension: **1024**
- Distance metric: **Cosine**
- No query instruction prefix — BGE-M3 is trained without a prefix, so both documents and queries are embedded verbatim.

The dense path is the default retrieval mode today (`return_sparse=False` in the embedder).

## Hybrid mode (dense + sparse)

BGE-M3 also emits **sparse** lexical weights (`lexical_weights`) for hybrid retrieval
(dense + sparse). This improves exact-entity queries (e.g. error codes, identifiers)
without changing the Cosine dense geometry. ColBERT multi-vectors are also supported by the model but not currently used.
