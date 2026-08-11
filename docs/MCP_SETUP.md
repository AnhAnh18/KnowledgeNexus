# 🔌 KnowledgeNexus MCP Server - Setup Guide

Quick setup guide to connect **Claude Code**, **Gemini CLI**, **Cline**, and **Claude Desktop** to the KnowledgeNexus MCP Server.

## 📍 Server URL

The MCP server is running at:

```
http://<SERVER_LAN_IP>:8787/mcp
```

Where `<SERVER_LAN_IP>` is the **IP address of the machine running the MCP server** (not your client machine).

### 🖥️ Current Server

The KnowledgeNexus MCP server is running on:

```
http://107.98.74.75:8787/mcp
```

## 🔧 Setup Instructions by LLM

### Claude Code

#### Option 1: CLI (Recommended)

```bash
claude mcp add knowledgenexus --transport http http://107.98.74.75:8787/mcp
```

Or replace `107.98.74.75` with your server's IP if different.

Verify:

```bash
claude mcp list
```

#### Option 2: Edit config file

Create or edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "knowledgenexus": {
      "type": "http",
      "url": "http://107.98.74.75:8787/mcp"
    }
  }
}
```

---

### Gemini CLI

#### Option 1: CLI

```bash
gemini mcp add knowledgenexus http://107.98.74.75:8787/mcp -t http
```

Verify:

```bash
gemini mcp list
```

#### Option 2: Edit config file

Edit `.gemini/settings.json` in your project root:

```json
{
  "mcpServers": {
    "knowledgenexus": {
      "type": "http",
      "url": "http://107.98.74.75:8787/mcp"
    }
  }
}
```

---

### Codex CLI

#### Option 1: CLI

```bash
codex mcp add knowledgenexus http://107.98.74.75:8787/mcp -t http
```

Verify:

```bash
codex mcp list
```

#### Option 2: Edit config file

Edit `~/.codex/config.toml`:

```toml
[mcp_servers.knowledgenexus]
type = "http"
url = "http://107.98.74.75:8787/mcp"
```

---

### Cline (VS Code)

1. Open the Cline MCP settings file:

| OS | Path |
|----|------|
| **Windows** | `%APPDATA%/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json` |
| **macOS** | `~/Library/Application Support/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json` |
| **Linux** | `~/.config/Code/User/globalStorage/cline-sr.cline-sr/settings/cline_mcp_settings.json` |

2. Add to `mcpServers`:

```json
{
  "knowledgenexus": {
    "disabled": false,
    "timeout": 60,
    "type": "http",
    "url": "http://107.98.74.75:8787/mcp"
  }
}
```

3. Save the file and restart Cline or reload VS Code

---

### Claude Desktop

1. Edit the config file:

| OS | Path |
|----|------|
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |

2. Add to `mcpServers`:

```json
{
  "mcpServers": {
    "knowledgenexus": {
      "type": "http",
      "url": "http://107.98.74.75:8787/mcp"
    }
  }
}
```

3. Fully quit and reopen Claude Desktop

---

## ✅ Verify Connection

After setup, test the connection:

```bash
# Test from terminal
curl -X POST http://107.98.74.75:8787/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    },
    "id": 1
  }'
```

✅ If you see a JSON response with `serverInfo`, the connection is working!

*Replace `107.98.74.75` with your server's IP if different.*

---

## ❓ Troubleshooting

### Connection refused or timeout

1. **Check MCP server is running:**
   ```bash
   # On the server machine, check port 8787 is listening
   netstat -ano | findstr ":8787"
   ```

2. **Check Windows Firewall (if needed):**
   ```cmd
   netsh advfirewall firewall add rule name="KnowledgeNexus MCP" dir=in action=allow protocol=TCP localport=8787
   ```

3. **Verify IP address:**
   - Use correct LAN IP (not `localhost` or `127.0.0.1` from remote machines)
   - Run `ipconfig` to find your IPv4 address

### "Connected but no tools found"

1. Make sure REST API is running on `http://localhost:8000`:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

2. Check MCP server is actually started and logs show:
   ```
   KnowledgeNexus MCP server running on http://0.0.0.0:8787/mcp
   ```

3. Restart your MCP client (Cline, Claude Code, etc.)

---

## 🛠️ Available MCP Tools

Once connected, you can use these tools in your LLM:

| Tool | Description |
|------|-------------|
| **search** | Search KnowledgeNexus for knowledge chunks |
| **export_search_results** | Export search results to Markdown file |
| **list_documents** | List all documents with pagination |
| **export_documents_list** | Export document list to Markdown file |
| **get_store_stats** | View Qdrant vector DB + SQLite statistics |
| **health_check** | Check API connectivity and health |

### Example Usage

Ask your LLM:

> "Search KnowledgeNexus for information about machine learning"

The LLM will automatically use the `search` tool to find relevant knowledge chunks.

---

**Last updated:** 2026-08-11
