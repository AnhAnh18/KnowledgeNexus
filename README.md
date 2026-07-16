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

## Foundation workstream

The Foundation workstream in this repository builds the data-contract,
deterministic export, and source-ingestion boundary used by later indexing and
retrieval work. Its internal milestone labels, such as Foundation M5A or M5B,
are workstream-local and do not replace the product milestones above.

Current Foundation status:

- Foundation M0-M4: contracts, deterministic record construction, and
  full-snapshot export foundation complete.
- Foundation M5A: deployment-independent Confluence inventory core complete.
- Foundation M5B-0: Confluence Data Center response shape confirmed through a
  sanitized offline evidence packet.
- Foundation M5B-1: pure response parsing and metadata normalization complete.
- Foundation M5B-2: Data Center HTTP adapter and pagination complete.
- Foundation M5C: a small manually reviewed real inventory is the next step.

Install the dependencies used by the current Foundation implementation from the
repository root:

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest tests/foundation tests/shared -q
```

`rfc3339-validator` is a declared runtime dependency because the Foundation
schema validator enables JSON Schema `format: date-time` checking through
`jsonschema.FormatChecker`. It is not only a test dependency.

Foundation-specific repository areas are:

```text
contracts/foundation/          Foundation schemas and integration contracts
src/knowledgenexus/foundation/ Foundation domain, application, ports, adapters
src/knowledgenexus/shared/     Shared technical contract utilities
tests/foundation/              Foundation unit and integration tests
tests/shared/                  Shared contract utility tests
data/exports/                  Published Foundation snapshots (runtime, ignored)
```

Foundation publishes snapshots under
`data/exports/<dataset_name>/<dataset_version>/`. Later indexing code must
consume only these published exports, never Foundation raw or working
directories. The current Confluence work covers inventory metadata only; page
bodies, rendered HTML, comments, attachments, and permissions remain outside
the current milestone.

## License

Internal use.
