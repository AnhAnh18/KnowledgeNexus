# Qdrant HNSW Search Tuning

Approximate nearest neighbor search in Qdrant uses **HNSW**.

## Knobs

- Higher `ef` (search-time) → better recall, slower queries.
- Collection was created with Cosine distance and 1024-dim dense vectors.

Hybrid mode still uses HNSW for the dense branch; sparse search is a separate path before RRF fusion.
