# SqliteChunkRepo Hydrate Batch

**SqliteChunkRepo** stores full chunk rows and implements hydrate for scored slim hits.

## Rules

- Primary key is chunk id.
- Batch `get_by_ids` / hydrate avoids N+1 after Qdrant search.
- Empty content in Qdrant payload is expected; SQLite is source of truth for text.
