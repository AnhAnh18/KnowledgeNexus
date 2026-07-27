# BGE-M3 Sparse Lexical Weights

Besides dense 1024-d vectors, BGE-M3 can emit **sparse lexical_weights**.

## Hybrid enablement

1. Call encode with `return_sparse=True`.
2. Store sparse vectors in Qdrant alongside dense.
3. At query time run dense + sparse searches and fuse with **RRF**.

Until sparse is indexed, `return_sparse=False` keeps the system dense-only.
