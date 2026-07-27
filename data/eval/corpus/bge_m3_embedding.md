# BGE-M3 Embedding Profile

KnowledgeNexus uses **BAAI/bge-m3** for embeddings.

## Dense configuration (locked)

- Vector dimension: **1024**
- Distance metric: **Cosine**
- Query prefix for dense retrieval:
  `Represent this sentence for searching relevant passages:`

The dense path is the default retrieval mode today (`return_sparse=False` in the embedder).

## Future modes

BGE-M3 can also emit **sparse** lexical weights and ColBERT multi-vectors. Hybrid retrieval
(dense + sparse) is planned for improving exact entity queries without changing Cosine dense
geometry.
