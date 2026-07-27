# ChunkStorageService Hydrate Flow

After vector search returns slim hits, KnowledgeNexus must reload full chunk text.

## Component

`ChunkStorageService` coordinates SQLite and Qdrant:

1. Qdrant returns scored slim points (`chunk_id`, filter fields, score).
2. `ChunkStorageService` calls hydrate via the chunk repository.
3. Callers receive full `content` plus `core` and `extra` metadata.

## Why hydrate exists

Qdrant intentionally does not store full text. Hydrate is the join step that makes
retrieval results usable for CLI (`kn search`) and LLM context.
