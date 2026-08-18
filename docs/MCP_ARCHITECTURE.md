# KnowledgeNexus MCP Server Architecture

## Transport Types Supported

The KnowledgeNexus MCP server implements **2 transport types**:

### 1. **HTTP/StreamableHTTP** (Recommended for remote connections)

**Configuration**:
```typescript
const MCP_TRANSPORT = process.env.MCP_TRANSPORT || 'stdio'; // Set to 'http'
const MCP_HTTP_HOST = process.env.MCP_HTTP_HOST || '0.0.0.0';
const MCP_HTTP_PORT = parseInt(process.env.MCP_HTTP_PORT || '8787', 10);
const MCP_HTTP_ALLOWED_HOSTS = process.env.MCP_HTTP_ALLOWED_HOSTS; // Comma-separated
```

**Use case**: Connect from other machines on the network

**Startup** (on server machine 107.98.74.75):
```bash
# Direct HTTP mode
MCP_TRANSPORT=http MCP_HTTP_PORT=8787 node build/index.js

# With host restrictions (optional, for security)
MCP_TRANSPORT=http MCP_HTTP_HOST=107.98.74.75 MCP_HTTP_PORT=8787 node build/index.js
```

**Remote access URL**:
```
http://107.98.74.75:8787/mcp
```

**Features**:
- ✅ Session-based (persistent across requests via session ID)
- ✅ Handles Accept header injection (auto-fixes old MCP clients)
- ✅ Multi-client support (sessions isolated)
- ✅ Full HTTP semantics: POST for requests, DELETE for cleanup
- ❌ Plain HTTP (not HTTPS) — use behind reverse proxy in production

**Session lifecycle**:
1. Client sends POST to `/mcp` → New session created with unique ID
2. Server responds with `mcp-session-id` header
3. Client includes `mcp-session-id` in future requests → Reuse same session
4. Client sends DELETE → Server cleans up session

---

### 2. **Stdio** (Default)

**Use case**: Process-to-process communication (embedding in other tools)

**Startup**:
```bash
# Default (stdio mode)
node build/index.js

# Or explicitly
MCP_TRANSPORT=stdio node build/index.js
```

**Features**:
- ✅ Single process/client per instance
- ✅ No session overhead (stateless within process)
- ❌ Not suitable for remote connections
- ❌ Requires embedding in a parent process

---

## Tool Definitions

The MCP server exposes **6 tools**:

| Tool | Input | Output | Use Case |
|------|-------|--------|----------|
| **search** | `query` (string), `top_k` (1-50), `score_threshold` (0-1) | Ranked chunks with citations | Query-based RAG |
| **export_search_results** | Same as `search` + `output_path` | Markdown file path + metadata | Save results to file |
| **list_documents** | `limit` (1-1000), `offset` (0+) | Document list + pagination | Browse corpus |
| **export_documents_list** | `output_path` + optional `limit`, `offset` | Markdown file path | Export document index |
| **get_store_stats** | (none) | JSON stats object | Monitor Qdrant + SQLite |
| **health_check** | (none) | JSON health object | Verify API connectivity |

---

## Request Flow (HTTP Transport)

```
Client                          MCP Server                    Backend API
  │                                  │                              │
  ├─── POST /mcp               ──────┤                              │
  │     (initialize)                  ├──────── GET /health ────────┤
  │                                   │                              │
  │                          [New Session Created]                   │
  │<─── 200 OK + session-id ─────────┤                              │
  │                                   │                              │
  ├─── POST /mcp               ──────┤                              │
  │     (tool call w/ session-id)     ├──────── POST /retrieve ─────┤
  │                                   │                              │
  │                                   │<────── JSON response ────────┤
  │<─── 200 OK + results ────────────┤                              │
  │                                   │                              │
  ├─── DELETE /mcp (session-id) ─────┤                              │
  │     (cleanup)                     │                              │
  │<─── 200 OK ────────────────────────┤                              │
```

---

## API Dependency

Both transports forward tool calls to the **KnowledgeNexus REST API**:

```typescript
const API_BASE_URL = process.env.KNOWLEDGENEXUS_API_URL || 'http://localhost:8000';

// Calls made by MCP server to backend:
// GET  /api/v1/health
// GET  /api/v1/documents?limit=X&offset=Y
// POST /api/v1/retrieve (query, top_k, score_threshold, filters)
// GET  /api/v1/store/stats
```

**Required**: REST API must be running at `KNOWLEDGENEXUS_API_URL`

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HTTP_HOST` | `0.0.0.0` | Bind address (0.0.0.0 = all interfaces) |
| `MCP_HTTP_PORT` | `8787` | HTTP port |
| `MCP_HTTP_ALLOWED_HOSTS` | undefined | Comma-separated IP whitelist (optional) |
| `KNOWLEDGENEXUS_API_URL` | `http://localhost:8000` | Backend API URL |

---

## Connection Checklist

Before declaring "connected but no tools", verify:

- [ ] MCP server process is running (check logs)
- [ ] REST API is running and healthy (`curl http://localhost:8000/api/v1/health`)
- [ ] Client can reach `http://<server-ip>:8787/mcp` (firewall check)
- [ ] Client restarted after MCP server started (session refresh)
- [ ] Check MCP server stdout/stderr for connection errors

---

## Debugging

**Enable verbose logs** (from MCP server startup output):
```
KnowledgeNexus MCP server running on http://0.0.0.0:8787/mcp
API base URL: http://localhost:8000
```

**Test manually** (HTTP transport):
```bash
# Initialize session
curl -X POST http://localhost:8787/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"init","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# Example response:
# {"jsonrpc":"2.0","id":"init","result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"knowledgenexus-mcp","version":"0.1.0"}}}
```

Extract `mcp-session-id` header from response, then use it for tool calls:
```bash
# Call search tool
curl -X POST http://localhost:8787/mcp \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: <extracted-id>" \
  -d '{"jsonrpc":"2.0","id":"call","method":"tools/call","params":{"name":"search","arguments":{"query":"test"}}}'
```

---

*Last updated: 2026-08-10*
