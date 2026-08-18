# KnowledgeNexus

Clean Architecture RAG platform — hybrid **SQLite** (source of truth) + **Qdrant** (vector search).

## Architecture

- **Domain** (`packages/domain`): entities, ports, `source_metadata/` typed schemas
- **API** (`services/api`): FastAPI application, use cases, infrastructure adapters
- **Payload model**: `CoreChunkMetadata` (common) + `extra` dict (source-specific)

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Qdrant (native binary, port 6333)

## Setup

```bash
# Install dependencies
uv sync

# Copy environment template
cp .env.example .env
```

## Run Qdrant (native)

```bash
# Windows (scoop)
scoop install qdrant

# macOS
brew install qdrant

# Run
qdrant --config-path ./config/qdrant
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
uv run pytest tests/eval -q   # two-layer eval unit tests
```

## Project Structure

```
KnowledgeNexus/
├── src/         # Production Python code (knowledgenexus package)
├── mcp/         # MCP server (TypeScript/Node.js)
├── eval/        # Evaluation tooling (development only)
├── tests/       # Unit and integration tests
├── scripts/     # Utility scripts
├── data/        # Data files
├── docs/        # Documentation
├── config/      # Configuration files
└── docker/      # Docker configurations
```

## MCP Server (Cline Integration)

KnowledgeNexus includes an MCP server (`mcp/`) that bridges Cline with the RAG platform.

### Quick Setup

```bash
cd mcp
npm install
npm run build
```

See **[docs/MCP_SETUP.md](docs/MCP_SETUP.md)** for full setup instructions.

## Packaging & Deployment (Windows)

### What gets packaged?

| Directory | Included? |
|-----------|-----------|
| `src/` | ✅ Yes |
| `mcp/` | ✅ Yes |
| `start.bat` | ✅ Yes |
| `eval/`, `tests/`, `docs/` | ❌ No |

### Workflow

```powershell
# 1. Build the code package
.\scripts\package-code.ps1

# 2. Transfer packages/ to target machine

# 3. Start the system
.\start.bat start

# 4. Stop the system
.\start.bat stop

# 5. For code updates only
.\scripts\update-code.ps1
```

### Client Deployment Guide

**1. Configure environment (.env file):**

```bash
# Database - use absolute path outside repo
DATABASE_URL=sqlite:///D:/kn-data/knowledgenexus.db

# Embedding model - must point to local model folder (provided with package)
EMBEDDING_MODEL_PATH=D:/KnowledgeNexus_Models/bge-m3

# Reranker model (optional)
RERANKER_MODEL_PATH=D:/KnowledgeNexus_Models/bge-reranker-v2-m3

# Confluence snapshots - must be absolute path outside repo
CONFLUENCE_SNAPSHOT_ROOT=D:/kn-data/confluence-snapshots
```

**2. Create required directories:**

```powershell
mkdir D:\kn-data
mkdir D:\kn-data\confluence-snapshots
```

**3. Copy model folders (provided separately):**

```
D:/KnowledgeNexus_Models/
├── bge-m3/           # Embedding model
└── bge-reranker-v2-m3/  # Reranker model (optional)
```

> **Note:** Auto-download from HuggingFace is not supported. Model folders must be provided.

See **[docs/MCP_SETUP.md](docs/MCP_SETUP.md)** and **[docs/MCP_ARCHITECTURE.md](docs/MCP_ARCHITECTURE.md)** for details.

## Documentation

- **Two-layer Eval**: [docs/EVAL_TWO_LAYER.md](docs/EVAL_TWO_LAYER.md)
- **Search Quality Roadmap**: [docs/SEARCH_QUALITY_ROADMAP.md](docs/SEARCH_QUALITY_ROADMAP.md)
- **MCP Architecture**: [docs/MCP_ARCHITECTURE.md](docs/MCP_ARCHITECTURE.md)
- **Integration Guide**: [docs/INTEGRATION_GUIDE.md](docs/INTEGRATION_GUIDE.md)

## License

Internal use.
