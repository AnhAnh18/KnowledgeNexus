# Qdrant Slim Payload

KnowledgeNexus stores only filter fields in Qdrant. This is called the **slim payload**.

## Fields stored in Qdrant

- `chunk_id` (keyword)
- `document_id` (keyword)
- `source_type` (keyword)
- `source_id` (keyword)
- `chunk_index`
- `indexed_at` (datetime)

Full `content`, `title`, `url`, and `extra` stay in SQLite and are attached after search
through hydrate.

Do not put large prose into the Qdrant payload. Promote a field from `extra` to the slim
payload only when it is filtered frequently (for example `space_key`).
