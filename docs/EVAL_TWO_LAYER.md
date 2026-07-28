# Two-layer eval (Retrieval + Agent/Skill)

Measure search quality in two layers so you know whether to fix **index/retrieve** or **Skill query wording**.

| Layer | Input | Path | What it measures |
|-------|-------|------|------------------|
| **L1** | `search_query` (oracle) | `POST /api/v1/retrieve` | Chunking / embed / retrieve |
| **L2** | `user_question` → `plan()` | same retrieve API (as `kn search`) | Skill/query formulation |
| **Gap** | L1 − L2 | — | Loss from how the agent asks |

## Setup

1. Ingest the bundled eval corpus (stable `source_id` labels):

```bash
uv sync --extra embedding
uv run python scripts/ingest_eval_corpus.py
```

2. Start API: `uv run knowledgenexus`
3. Run:

```bash
uv sync
uv run kn-eval --layer all --label baseline
```

Golden: `data/eval/golden/queries.jsonl` (19 cases). Details: `data/eval/README.md`.
`match_on` defaults to `source_id` in `config/eval.yaml`.

Outputs:

- `data/eval/results/<timestamp>_<label>.json`
- `data/eval/results/LEADERBOARD.md` (auto-updated)

## Commands

```bash
uv run kn-eval --layer 1 --label retrieval-only
uv run kn-eval --layer 2 --label skill-path
uv run kn-eval --layer all --label after-skill-tweak
uv run kn-eval --golden tests/eval/fixtures/mini_queries.jsonl --label dry-run
```

Config: `config/eval.yaml` (override API with `KNOWLEDGENEXUS_API_URL`).

## How to read results

- Fix **retrieval/chunking** → watch **L1 Hit@10** (L2 usually moves too).
- Fix **Skill / plan()** → freeze index; expect **L1 flat**, **L2 up** or **Gap down**.
- `match_on: document_id` (default) is stabler across re-chunk than `chunk_id`.

## Code map

```text
src/knowledgenexus/eval/
  metrics.py, loader.py, config.py
  layer1_retrieval.py   # oracle query
  layer2_agent.py       # plan(user_question) → retrieve
  runner.py             # kn-eval entry
  compare.py            # LEADERBOARD.md
```

Unit tests (no API): `uv run pytest tests/eval -q`
