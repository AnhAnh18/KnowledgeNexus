# KnowledgeNexus MCP Server

MCP server bridge between Cline and the KnowledgeNexus RAG platform.

## 🎯 Purpose

Allows Cline to search knowledge stored in KnowledgeNexus and export results to Markdown files.

## 🛠️ Available Tools

| Tool | Description |
|------|-------------|
| `search` | Search KnowledgeNexus for relevant knowledge chunks |
| `export_search_results` | Search and export results to a `.md` file |
| `list_documents` | List all documents in KnowledgeNexus |
| `export_documents_list` | Export document list to a `.md` file |
| `get_store_stats` | Get storage statistics (Qdrant + SQLite) |
| `health_check` | Check platform health status |

## ⚙️ Configuration

Environment variable `KNOWLEDGENEXUS_API_URL` (default: `http://localhost:8000`).

## 📦 Build

```bash
cd mcp
npm install
npm run build
```

## 🔌 MCP Settings (Cline)

Add the following to your Cline MCP settings file:

**Windows:** `%APPDATA%/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json`
**macOS/Linux:** `~/.config/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json`

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

> **Note:** Replace `<ABSOLUTE_PATH_TO_PROJECT>` with the actual path to your KnowledgeNexus project root.

### Example (Windows)

```json
{
  "knowledgenexus-mcp": {
    "disabled": false,
    "timeout": 60,
    "type": "stdio",
    "command": "node",
    "args": ["D:/GitHub/KnowledgeNexus/mcp/build/index.js"],
    "env": {
      "KNOWLEDGENEXUS_API_URL": "http://localhost:8000"
    }
  }
}
```

### Example (macOS/Linux)

```json
{
  "knowledgenexus-mcp": {
    "disabled": false,
    "timeout": 60,
    "type": "stdio",
    "command": "node",
    "args": ["/home/user/projects/KnowledgeNexus/mcp/build/index.js"],
    "env": {
      "KNOWLEDGENEXUS_API_URL": "http://localhost:8000"
    }
  }
}
```

## 💡 Usage Examples

Ask Cline:
- "Search KnowledgeNexus for 'how to configure qdrant'"
- "Search for 'table layout performance' and export results to ./search-results.md"
- "List all documents in KnowledgeNexus"
- "Check the health of KnowledgeNexus"
