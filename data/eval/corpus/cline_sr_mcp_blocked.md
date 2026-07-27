# Cline SR MCP Blocked Workaround

**Cline SR** blocks custom MCP servers. KnowledgeNexus therefore uses Skill + CLI:

- Skill file: `.clinerules/skills/knowledgenexus-cli.md`
- Entry: `uv run kn …`

MCP under `mcp/` remains optional for environments that allow it; SR deployments should
prefer the agent CLI path.
