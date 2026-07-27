# Eval leaderboard (2-layer)

No runs yet. After the API is up and golden IDs are filled:

```bash
uv sync
uv run knowledgenexus   # terminal 1 — API
uv run kn-eval --layer all --label baseline
```

L1 = oracle `search_query` → retrieve.  
L2 = Skill-like `plan(user_question)` → retrieve.  
Gap = L1 − L2.
