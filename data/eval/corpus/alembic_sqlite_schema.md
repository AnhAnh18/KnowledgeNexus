# Alembic SQLite Schema Notes

Indexing persistence uses **Alembic** migrations against SQLite under `data/index/`.

## Operator tips

- Run `uv run alembic upgrade head` after pull.
- Do not hand-edit the SQLite file while the API is writing chunks.
- Qdrant vectors are not migrated by Alembic; rebuilding the collection requires re-embed.

Schema ownership stays in the indexing infrastructure database models, not in the agent CLI.
