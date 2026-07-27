# Agent CLI kn search Skill

Cline uses the KnowledgeNexus **Skill** to call the agent CLI.

## Primary command

```bash
uv run kn search "QUERY" --top-k 5
```

The Skill must keep proper nouns and error codes inside `QUERY`. Do not call foundation
ingest CLIs for knowledge lookup. Supporting commands: `list-docs`, `stats`, `health`.
