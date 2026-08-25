# Eval corpus + golden (hybrid A/B)

## Contents

| Path                              |                 Role                           |
|-----------------------------------|------------------------------------------------|
| `data/eval/corpus/*.md`           | **18** short docs (entities + semantic prose)  |
| `data/eval/golden/queries.jsonl`  | **50** labeled queries (`relevant_source_ids`) |
| `scripts/ingest_eval_corpus.py`   | Deterministic ingest for this corpus           |

`config/eval.yaml` uses `match_on: source_id` so labels survive re-ingest.

## Golden breakdown (50)

| Prefix | Count | Focus |
|--------|------:|-------|
| `ex-*` | 25 | Exact tokens / IDs — **hybrid should help most** (`hybrid-sensitive`) |
| `sem-*` | 15 | Paraphrase — dense should work; hybrid must not regress |
| `mix-*` | 10 | Entity + wording mixed |

Đáp án Hit@k = field **`relevant_source_ids`** (cùng file). Điểm Hit@k do `kn-eval` tính.

## Tags

| Tag | Purpose |
|-----|---------|
| `exact-entity` | Rare tokens (`ERR_AUTH_401`, `RetrieveChunksUseCase`, …) |
| `hybrid-sensitive` | Subset expected to improve after dense+sparse |
| `semantic` | Paraphrase / meaning |
| `mixed` | Both signals |

## Workflow before / after hybrid

```bash
# 1) Re-ingest full eval corpus (18 docs)
uv sync --extra embedding
uv run python scripts/ingest_eval_corpus.py

# 2) API up
uv run knowledgenexus

# 3) Dense baseline
uv run kn-eval --layer 1 --label dense-before-hybrid

# 4) After hybrid + re-ingest
uv run kn-eval --layer 1 --label hybrid-rrf
```

Compare `data/eval/results/LEADERBOARD.md`. Inspect per-case JSON for tags `hybrid-sensitive` / `exact-entity`.

## Chunk-budget benchmark

Use the committed corpus to compare the candidate chunk budgets without changing
the active Foundation profile:

```bash
python scripts/benchmark_eval_chunk_profiles.py --output data/eval/results/chunk-budget-report.json
```

For production-representative counts, supply the explicit pinned BGE-M3
`tokenizer.json` bundle with `--tokenizer-json`. Without it, the report uses a
whitespace approximation and is useful only for structural comparison. The
golden queries are source-level labels, so this command does not claim a
retrieval-quality winner; use a chunk-labelled corpus before changing the
active profile. The bundled 18-document corpus is intentionally short and
currently produces the same chunk count for every candidate; use an approved
long-document corpus (or an external operator-provided corpus) for a decision.
