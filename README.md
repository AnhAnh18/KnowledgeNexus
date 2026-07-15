# KnowledgeNexus

Clean Architecture RAG platform — hybrid **SQLite** (source of truth) + **Qdrant** (vector search).

## Architecture

- **Domain** (`packages/domain`): entities, ports, `source_metadata/` typed schemas
- **API** (`services/api`): FastAPI application, use cases, infrastructure adapters
- **Payload model**: `CoreChunkMetadata` (common) + `extra` dict (source-specific)

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Qdrant (native binary, port 6333) — see below

## Setup

```bash
# Install dependencies
uv sync

# Copy environment template
cp .env.example .env
```

## Run Qdrant (native — no Docker until M6)

Download from [Qdrant releases](https://github.com/qdrant/qdrant/releases) or:

```bash
# Windows (scoop)
scoop install qdrant

# macOS
brew install qdrant

# Run
qdrant --config-path ./config/qdrant  # or default on :6333
```

## Run API

```bash
uv run knowledgenexus
# or
uv run uvicorn knowledgenexus.main:app --reload --port 8000
```

Health: http://localhost:8000/api/v1/health

## Tests

```bash
uv run pytest
```

## Project structure

```
contracts/openapi.yaml     # API contract (M0)
config/                    # Qdrant collection schema, defaults
packages/domain/           # Domain layer (no external deps)
services/api/              # FastAPI service
tests/                     # Unit + integration tests
```

## Milestones

| # | Deliverable |
|---|-------------|
| M0 | Foundation — domain, ports, OpenAPI, settings ✅ |
| M1 | SQLite repos + Qdrant adapter + Store API |
| M2 | Chunker, BGE-M3, Confluence parser |
| M3 | MVP-1 — Ingest E2E |
| M4 | MVP-2 — Retrieve + search |
| M5 | MVP-3 — RAG chat |
| M6 | Docker, MCP/URL/file connectors, PostgreSQL |

## License

Internal use.
