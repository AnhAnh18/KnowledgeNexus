---
name: knowledge-nexus
description: Search and interact with the KnowledgeNexus RAG platform via the `kn` CLI — retrieve knowledge chunks, list documents, get stats, and check API health.
alwaysApply: true
---

# knowledge-nexus

Instructions for the AI agent to search and interact with the KnowledgeNexus RAG platform using the `kn` command-line tool.

## Usage

Activate this skill when the user asks to:
- Search for knowledge, documentation, or code patterns
- Query the KnowledgeNexus RAG platform
- List documents in the knowledge base
- Get storage statistics
- Check API health status
- Any question that requires looking up information from indexed documents

## Prerequisites

Before using these commands, ensure:
1. KnowledgeNexus API is running
   - Start with: `uv run knowledgenexus` or `python -m knowledgenexus`
2. Qdrant vector DB is running at `http://localhost:6333`
3. Dependencies installed: `uv sync` (so `kn` entry point exists)
4. API URL is configured — the CLI auto-loads `.env` from the repo root:
   - Copy `.env.example` to `.env`: `cp .env.example .env`
   - `KNOWLEDGENEXUS_API_URL` in `.env` already points to the shared API server
   - To override locally, set the `KNOWLEDGENEXUS_API_URL` environment variable

## Steps

### 1. Identify intent

- "Search for..." / "Find..." / "Look up..." → Use `search` command
- "What documents..." / "List documents..." → Use `list-docs` command
- "How many..." / "Statistics..." → Use `stats` command
- "Is the API running?" / "Health check" → Use `health` command

### 2. Search Knowledge (MOST COMMON)

**When:** User asks to search/find/look up information or knowledge

```bash
uv run kn search "QUERY" --top-k 5
```

**Parameters:**
- `QUERY` - The search query text (required). Keep proper nouns, API names, and error codes; drop chat filler.
- `--top-k N` - Number of results (default: 5, max: 50)
- `--score-threshold X` - Min similarity score (default: 0.0, range: 0.0-1.0)

**Example:**

```bash
uv run kn search "table layout performance" --top-k 10
```

### 3. List Documents

**When:** User wants to see what documents are indexed

```bash
uv run kn list-docs --limit 100 --offset 0
```

### 4. Get Store Statistics

**When:** User asks about storage stats, vector DB info, or document counts

```bash
uv run kn stats
```

### 5. Health Check

**When:** User reports API issues or wants to verify system health

```bash
uv run kn health
```

### 6. Read output and synthesize answer

- Read the command output and synthesize a natural language answer
- Cite sources — include file paths, line numbers, and titles from results

## Output Format

### Search Results

```
Found 5 result(s) for "table layout".

--- Result 1 (score: 0.8945) ---
Title: SPenSDK Table Layout Doc
Source: markdown / doc_456
File: docs/Table.md:42-156

Content:
TableLayout class handles layout and rendering of tables...
```

### List Documents

```
Documents: 42 total (showing 10, offset 0)

1. SPenSDK Table Layout Doc
   ID: doc_456
   Source: markdown / doc_456
   Created: 2026-05-25T10:00:00
```

## Environment Variables

- `KNOWLEDGENEXUS_API_URL` - API base URL (default: `http://localhost:8000`)
- Auto-loaded from `.env` file in the repo root — no manual setup needed
- To override: set the `KNOWLEDGENEXUS_API_URL` environment variable before running `kn`

## Error Handling

If you see connection errors:

```
❌ Connection Error: [Errno 111] Connection refused
   Is KnowledgeNexus API running at http://localhost:8000?
```

→ Tell the user to start the API: `uv run knowledgenexus`

If you see API errors:

```
❌ API Error (404): Not Found
```

→ Check the endpoint and parameters

## Notes

- Agent CLI lives under `src/knowledgenexus/presentation/cli/agent/` (not foundation ingest CLIs)
- Do **not** call `foundation/cli/*` for knowledge search
- Commands communicate via stdout — Cline reads output directly
- For large result sets, use `--top-k` to limit output size
- **First search may take 30-60 seconds** (BGE-M3 embedding model loads on first call)
- Subsequent searches are much faster (model already loaded in API memory)
- If search times out, the command runs in background — check the log file for results
- `list-docs`, `stats`, and `health` are fast (no embedding needed)
- Equivalent module form (if needed): `uv run python -m knowledgenexus.presentation.cli.agent search "QUERY"`
