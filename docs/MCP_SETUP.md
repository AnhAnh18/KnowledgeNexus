# MCP Server Setup Guide

Guide to set up the KnowledgeNexus MCP Server to connect Cline with the KnowledgeNexus RAG platform.

## 📋 Overview

The KnowledgeNexus MCP Server is a bridge between Cline and the KnowledgeNexus RAG platform. It allows Cline to:

- **Search** knowledge from KnowledgeNexus
- **Export** search results to Markdown files
- **List** documents in KnowledgeNexus
- **Check health** of the platform

The MCP server lives inside the project at `mcp/` — anyone who clones the repo can use it.

## 📦 Installation

### 1. Install dependencies and build

```bash
cd mcp
npm install
npm run build
```

After building, the file `mcp/build/index.js` will be created.

### 2. Configure Cline MCP Settings

Open the Cline MCP settings file:

| OS | Path |
|----|------|
| **Windows** | `%APPDATA%/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json` |
| **macOS** | `~/Library/Application Support/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json` |
| **Linux** | `~/.config/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json` |

Add the following configuration to `mcpServers`:

```json
{
  "knowledgenexus-mcp": {
    "disabled": false,
    "timeout": 60,
    "type": "stdio",
    "command": "node",
    "args": ["<ABSOLUTE_PATH_TO_PROJECT>/mcp/build/index.js"],
    "env": {
      "KNOWLEDGENEXUS_API_URL": "http://localhost:8000"
    }
  }
}
```

> ⚠️ **Important:** Replace `<ABSOLUTE_PATH_TO_PROJECT>` with the absolute path to the KnowledgeNexus project root directory on your machine.

### 3. Start the KnowledgeNexus API

The MCP server requires the KnowledgeNexus API to be running:

```bash
# From project root
uv run knowledgenexus
# or
uv run uvicorn knowledgenexus.main:app --reload --port 8000
```

### 4. Restart Cline

After updating the MCP settings, restart Cline (or reload VS Code) so the MCP server is loaded.

## 🛠️ Available Tools

| Tool | Description | Parameters |
|------|-------------|-----------|
| `search` | Search knowledge chunks | `query` (required), `top_k`, `score_threshold` |
| `export_search_results` | Search + export to `.md` | `query`, `output_path` (required), `top_k`, `score_threshold` |
| `list_documents` | List all documents | `limit`, `offset` |
| `export_documents_list` | Export document list to `.md` | `output_path` (required), `limit`, `offset` |
| `get_store_stats` | Storage statistics (Qdrant + SQLite) | — |
| `health_check` | Check platform health | — |

## 💡 Usage Examples

Ask Cline:

- "Search KnowledgeNexus for 'how to configure qdrant'"
- "Search for 'table layout performance' and export results to ./search-results.md"
- "List all documents in KnowledgeNexus"
- "Check the health of KnowledgeNexus"
- "Get store stats from KnowledgeNexus"

## 🔧 Troubleshooting

### MCP server cannot connect

1. **Check build exists:** Ensure `mcp/build/index.js` was created after `npm run build`
2. **Check path:** The path in `args` must be an **absolute path** and correct
3. **Check Node.js:** Ensure `node` is in your PATH (`node --version`)

### API error when calling a tool

1. **Check API is running:** `curl http://localhost:8000/api/v1/health`
2. **Check port:** The API runs on port 8000 by default; if different, update `KNOWLEDGENEXUS_API_URL`
3. **Check Qdrant:** Ensure Qdrant is running on port 6333

### Rebuild after code changes

```bash
cd mcp
npm run build
```

Then restart Cline to reload the MCP server.

## 📁 MCP Directory Structure

```
mcp/
├── src/
│   └── index.ts          # MCP server source code
├── build/                # Build output (gitignored)
│   └── index.js
├── package.json
├── tsconfig.json
└── README.md
```

## 🔄 Development Workflow

```bash
# Watch mode - auto-rebuild on code changes
cd mcp
npm run dev

# Once code is stable, build for production
npm run build
```

---

*Last updated: 2026-07-22*
