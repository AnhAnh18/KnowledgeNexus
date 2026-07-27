# RetrieveChunksUseCase

The retrieval bounded context exposes **RetrieveChunksUseCase**.

## Flow

1. `embed_query` via BGE-M3 (dense today).
2. `RetrievalSearchPort.search` against Qdrant.
3. Optional `score_threshold` filter on scores.
4. `hydrate` full chunk content from SQLite.

API mapping: `POST /api/v1/retrieve` builds a `RetrieveRequest` and calls this use case.
