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
| `mcp/` | ✅ Yes (without `node_modules/`) |
| `start.bat` | ✅ Yes |
| `eval/`, `tests/`, `docs/` | ❌ No |

> **Note:** `mcp/node_modules/` is excluded. Client runs `npm install` in `mcp/` folder after extraction.

### Workflow

```powershell
# 1. Build the code package
.\scripts\package-code.ps1

# 2. Transfer zip file to target machine

# 3. Start the system
.\start.bat start
```

### Client Deployment Guide

**KnowledgeNexus_Data folder will be provided** containing the complete data structure.

**1. Configure environment (.env file):**

```bash
# Database - absolute path outside repo
DATABASE_URL=sqlite:///D:/KnowledgeNexus_Data/knowledgenexus.db

# Embedding model - provided in KnowledgeNexus_Data/models
EMBEDDING_MODEL_PATH=D:/KnowledgeNexus_Data/models/bge-m3

# Reranker model (optional) - provided in KnowledgeNexus_Data/models
RERANKER_MODEL_PATH=D:/KnowledgeNexus_Data/models/bge-reranker-v2-m3

# Confluence snapshots - absolute path outside repo
CONFLUENCE_SNAPSHOT_ROOT=D:/KnowledgeNexus_Data/confluence-snapshots
```

**2. KnowledgeNexus_Data structure (provided):**

```
D:/KnowledgeNexus_Data/
├── knowledgenexus.db          # SQLite database (created on first run)
├── models/
│   ├── bge-m3/                # Embedding model (provided)
│   └── bge-reranker-v2-m3/    # Reranker model (optional, provided)
└── confluence-snapshots/      # Confluence raw data
```

> **Note:** Auto-download from HuggingFace is not supported. All model folders are provided with KnowledgeNexus_Data.

### Client Update Guide

**To update client code to a new version:**

**Developer sends:**
```
knowledgenexus-code-v1.0.1.zip    (new version package)
```

**Client steps:**
```powershell
# 1. Copy the new zip file to the updates/ folder
D:/KnowledgeNexus/updates/knowledgenexus-code-v1.0.1.zip

# 2. Run the update script
.\updates\update-code.ps1

# 3. Restart the system
.\start.bat stop
.\start.bat start
```

**What gets updated:**
- ✅ `src/` - Application code
- ✅ `mcp/` - MCP server (client runs `npm install` after update)
- ✅ `requirements.txt` - Python dependencies (auto-installed)
- ✅ `start.bat` - Start script

**What is preserved:**
- ✅ `.env` - Client configuration and secrets
- ✅ `KnowledgeNexus_Data/` - Database and models
- ✅ `data/` - Runtime data

See **[docs/MCP_SETUP.md](docs/MCP_SETUP.md)** and **[docs/MCP_ARCHITECTURE.md](docs/MCP_ARCHITECTURE.md)** for details.

## Documentation

- **Two-layer Eval**: [docs/EVAL_TWO_LAYER.md](docs/EVAL_TWO_LAYER.md)
- **Search Quality Roadmap**: [docs/SEARCH_QUALITY_ROADMAP.md](docs/SEARCH_QUALITY_ROADMAP.md)
- **MCP Architecture**: [docs/MCP_ARCHITECTURE.md](docs/MCP_ARCHITECTURE.md)
- **Integration Guide**: [docs/INTEGRATION_GUIDE.md](docs/INTEGRATION_GUIDE.md)

## License

Internal use.
