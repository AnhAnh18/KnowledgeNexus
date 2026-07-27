# Cline SR Integration Guide

## Overview

Guide for integrating Cline SR with the KnowledgeNexus RAG platform.

**Problem:** Cline SR (Samsung Research version) does not allow custom MCP servers.  
**Solution:** Agent CLI (`kn`) + Skill as a replacement for MCP hooks.

---

## Architecture

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   User      │ ──►  │     Cline SR     │ ──►  │  kn (agent CLI) │ ──►  │ KnowledgeNexus  │
│   asks      │      │  (Claude AI)     │      │  presentation/  │      │     API         │
└─────────────┘      └──────────────────┘      │  cli/agent      │      └─────────────────┘
                              │                └─────────────────┘               │
                              │ 1. Read Skill                                    │
                              │ 2. Match intent                                  ▼
                              │ 3. Execute: uv run kn …                   ┌─────────────┐
                              │                                           │  Qdrant +   │
                              ▼                                           │   SQLite    │
                      4. Read stdout                                      └─────────────┘
                      5. Synthesize answer
```

The Agent CLI does **not** use `foundation/cli/*` (ingest/ops). It only calls read APIs via HTTP.

---

## Components

### 1. Agent CLI: `src/knowledgenexus/presentation/cli/agent/`

- Entry: `uv run kn <command>` (console script) or  
  `uv run python -m knowledgenexus.presentation.cli.agent <command>`
- Stdlib HTTP client → FastAPI (`/retrieve`, `/documents`, `/store/stats`, `/health`)
- Commands: `search`, `list-docs`, `stats`, `health`

### 2. Skill: `.clinerules/skills/knowledgenexus-cli.md`

- Instructs Cline when and how to call `kn`
- Automatically loaded when Cline starts

---

## Usage

### Step 1: Start KnowledgeNexus API

```bash
uv run knowledgenexus
```

### Step 2: Verify

```bash
uv run kn health
```

### Step 3: Ask Cline

```
User: "Find information about table layout in the system"
→ Cline reads Skill → uv run kn search "table layout"
→ Cline reads output → synthesizes answer
```

---

## Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `search` | Search knowledge chunks | `uv run kn search "query" --top-k 5` |
| `list-docs` | List documents | `uv run kn list-docs --limit 10` |
| `stats` | Get store statistics | `uv run kn stats` |
| `health` | Health check | `uv run kn health` |

Env: `KNOWLEDGENEXUS_API_URL` (default `http://localhost:8000`).

---

## Limitations vs MCP

| Aspect              | MCP Hook (blocked)  | CLI + Skill (working) |
|---------------------|---------------------|----------------------|
| Cline SR support    | ❌ Blocked          | ✅ Working          |
| Auto-discovery      | ✅ Via ListTools    | ✅ Via Skill        |
| Protocol            | JSON-RPC            | CLI args + stdout    |
| First search speed  | Fast                | Slow (BGE-M3 load)   |
| Subsequent searches | Fast                | Fast                 |

---

## Troubleshooting

### Connection refused

```
❌ Connection Error: ...
```

**Fix:** `uv run knowledgenexus`

### Search timeout

The first search is slow due to BGE-M3 model loading. The command may run in the background — check the log.

### No results

Ingest documents before searching.

---

*Last updated: 2026-07-24*
