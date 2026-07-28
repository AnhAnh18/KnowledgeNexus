# Search Quality Improvement Roadmap

This document tracks search quality improvements for KnowledgeNexus.  
Shared across the team: update status / owner / eval link after each milestone.

**Current architecture:** User → Cline Skill → `uv run kn …` → API → Qdrant + SQLite hydrate  

**Embedding locked:** BGE-M3 dense, Cosine 1024 (unchanged in phases 1–5).

---

## Priority order (agreed)

| # | Item | Short-term goal | Status | Owner | Target |
|---|------|-----------------|--------|-------|--------|
| 1 | Chunking + text quality | Sufficient context; clean text; 1 clear profile | `todo` | | |
| 2 | Skill query | Correct CLI/params; preserve entities; Gap L1−L2 ↓ | `todo` | | |
| 3 | Field / filter Qdrant | Only index frequently filtered fields; CLI/Skill call correctly | `todo` | | |
| 4 | Hybrid dense + sparse | When eval misses exact matches; A/B via `kn-eval` | `todo` | | |
| 5 | Dedup → multi-query → rerank | After 1–4 are stable; metric conditions met | `later` | | |
| 6 | Fine-tune / change embed model | Last resort; unlikely to do early | `later` | | |

Suggested statuses: `todo` | `in_progress` | `blocked` | `done` | `later` | `skipped`

---

## Two phases (quick reminder)

```text
INDEX TIME:  Document → Chunking → Embed dense[+sparse] → Qdrant + SQLite
QUERY TIME:  User → Skill/kn → Embed query → Dense/Sparse/Hybrid → (rerank) → Hydrate
```

Search improvements span **both phases**, not just the query-time search call.

---

## Required eval (shared measurement)

| Tool | Path / command |
|------|-----------------|
| Golden | `data/eval/golden/queries.jsonl` |
| Eval corpus | `data/eval/corpus/` |
| Ingest corpus | `uv run python scripts/ingest_eval_corpus.py` |
| Runner | `uv run kn-eval --layer 1\|2\|all --label <name>` |
| Leaderboard | `data/eval/results/LEADERBOARD.md` |
| Eval docs | `docs/EVAL_TWO_LAYER.md`, `data/eval/README.md` |

**Two layers:**

| Layer | Input | What it measures |
|-------|-------|------------------|
| L1 | `search_query` (oracle) | Chunk / embed / retrieve / hybrid |
| L2 | `user_question` → `plan()` | Skill / CLI invocation |
| Gap | L1 − L2 | Loss from Skill query formulation |

`match_on: source_id` (`config/eval.yaml`) — stable across re-chunking.

**Important golden tags:** `exact-entity`, `hybrid-sensitive`, `semantic`.

### Leaderboard label conventions

| When you finish… | Run with `--label` |
|-------------------|-------------------|
| Chunk baseline | `chunk-baseline` |
| Skill fix | `skill-vN` (freeze index) |
| Filter hardening | `filter-source-type` (e.g.) |
| Before hybrid | `dense-before-hybrid` |
| After hybrid | `hybrid-rrf` |

---

## Step 1 — Chunking + text quality

### Goal

One clear chunk profile; clean normalized text; every chunk change → re-ingest + `kn-eval --layer 1`.

### Current state

- Spec: `contracts/foundation/CHUNKING_SPEC.md` (`chunker_version` 1.2.0, medium provisional).
- Markdown/eval scripts (`ingest_*.py`) chunk by **character** 1500/150 — differs from Foundation token budget → needs alignment / documentation.

### Checklist

- [ ] 1A. Finalize production path vs demo script; document the active profile
- [ ] 1B. Normalization checklist per source (Confluence / Markdown / code)
- [ ] 1C. Tune **one variable at a time** (if allowed); prioritize heading/paragraph boundaries
- [ ] 1D. `ingest_eval_corpus` + `kn-eval --layer 1 --label chunk-baseline`
- [ ] Compare Hit@10 overall + slice `semantic` / `exact-entity`

### Done when

- [ ] Official chunk profile is documented  
- [ ] `chunk-baseline` row exists on LEADERBOARD  
- [ ] Team knows: changing chunk = mandatory re-ingest  

### Notes / links

- Owner:  
- PR / commit:  
- Leaderboard label: `chunk-baseline`  
- Notes:

---

## Step 2 — Skill query

### Goal

Skill calls `kn` correctly; query preserves proper nouns / error codes; Gap ↓ on `--layer all`.

### Current state

- Skill: `.clinerules/skills/knowledgenexus-cli.md`
- CLI: `src/knowledgenexus/presentation/cli/agent/`
- Eval L2: `src/knowledgenexus/eval/layer2_agent.py` (`plan()`)

### Checklist

- [ ] 2A. Tighten Skill: intent→command, rules for writing QUERY, default `--top-k` (8–10), default threshold 0
- [ ] 2B. Sync eval `plan()` with Skill rules
- [ ] 2C. (Prep for step 3) `--source-type` on `kn search` → `filters` API
- [ ] 2D. Add real fail-cases to golden (`source: manual_fail`)
- [ ] `kn-eval --layer all --label skill-vN` (freeze index)

### Done when

- [ ] Skill version recorded (`skill-vN`)  
- [ ] L1 stays flat; L2 ↑ or Gap ↓  
- [ ] No foundation ingest CLI used for search  

### Notes / links

- Owner:  
- PR / commit:  
- Leaderboard label:  
- Notes:

---

## Step 3 — Field / filter Qdrant

### Goal

Filter on correctly indexed fields; only promote fields that are actually used; payload stays slim.

### Current state (slim + indexed)

`chunk_id`, `document_id`, `source_type`, `source_id`, `chunk_index`, `indexed_at`  
→ `config/qdrant.collection.yaml` / `qdrant_store._slim_payload`

`space_key` / paths… are typically in SQLite `extra` — **not yet** promoted.

### Checklist

- [ ] 3A. Filter demand table (from Skill/API logs) — decide promote / don't
- [ ] 3B. Harden existing filters (`source_type`, …) + test + golden with `filters`
- [ ] 3C. Promote field (e.g. `space_key`) **only if 3A meets threshold** + re-upsert
- [ ] 3D. Integrity: count parity, hydrate 100%, payload allowlist test

### Field decision table (fill in during 3A)

| Field | % requests with filter? | Slim+indexed? | Decision |
|-------|--------------------------|---------------|----------|
| `source_type` | | yes | keep |
| `source_id` | | yes | keep |
| `space_key` | | no | |
| `repo` / `file_path` | | no | |
| `title` / `content` | — | no | **do not** put in Qdrant |

### Done when

- [ ] Field table has decisions  
- [ ] CLI/Skill filters on correct indexed keys  
- [ ] No payload bloat "just in case"  

### Notes / links

- Owner:  
- PR / commit:  
- Leaderboard label:  
- Notes:

---

## Step 4 — Hybrid (dense + sparse)

### Goal

BGE-M3 dense + **BGE-M3 sparse** + RRF; switch default only when A/B wins on golden.

### Gate (mandatory before coding hybrid)

- [ ] `chunk-baseline` and at least one `skill-vN` exist on leaderboard  
- [ ] `exact-entity` / `hybrid-sensitive` tags still miss (or real named-entity fail cases)  
- [ ] Skill already preserves entities in QUERY  

If exact matches are already good with dense → **defer** step 4 (`skipped` / `later`).

### Checklist

- [ ] 4A. `kn-eval --layer 1 --label dense-before-hybrid`
- [ ] 4B. Embedder `return_sparse=True` + bundle dense/sparse (doc + query)
- [ ] 4C. Qdrant named dense + sparse; upsert both; flag `retrieval.mode: dense|hybrid` (default dense)
- [ ] 4D. Dual search + RRF (`k≈60`, prefetch≈40) → hydrate as before
- [ ] 4E. Re-ingest + `kn-eval --layer 1 --label hybrid-rrf`
- [ ] 4F. `kn-eval --layer all --label hybrid-rrf-with-skill`
- [ ] Decision: enable hybrid default **only if** overall doesn't drop significantly **and** `hybrid-sensitive` ↑

### Done when

- [ ] Dense/hybrid flag works  
- [ ] A/B on LEADERBOARD  
- [ ] Docs: changing sparse = must re-embed  

### Notes / links

- Owner:  
- PR / commit:  
- Leaderboard labels: `dense-before-hybrid` / `hybrid-rrf`  
- Notes:

---

## Steps 5–6 (not in this phase)

| # | Task | Opening condition |
|---|------|-------------------|
| 5a | Dedup by `document_id` in top-k | Top-k noisy with many chunks from same doc |
| 5b | Multi-query (Skill) | Multi-intent questions; close to step 2 |
| 5c | Rerank | High Hit@20 but low Hit@5 / MRR |
| 6 | Fine-tune / change model | Exhausted room in 1–5; needs eval justification |

---

## Suggested schedule

| Week | Focus | Expected output |
|------|-------|-----------------|
| W1 | Step 1 | Chunk profile + `chunk-baseline` |
| W1–W2 | Step 2 | `skill-vN` + Gap ↓ |
| W2 | Step 3 | Field table + filter hardening |
| W3 | Step 4 (if gate passes) | Hybrid flag + A/B |

Work **sequentially** through gates. When measuring Skill: **freeze index**. When measuring chunk/hybrid: re-ingest before eval.

---

## Update log (newest on top)

| Date | Who | Change | Eval label |
|------|-----|--------|------------|
| 2026-07-24 | — | Created roadmap + golden/eval harness | — |
| | | | |

---

## Quick links

| Document | Path |
|----------|------|
| Skill CLI | `.clinerules/skills/knowledgenexus-cli.md` |
| Cline integration | `docs/CLINE_INTEGRATION.md` |
| Eval 2-layer | `docs/EVAL_TWO_LAYER.md` |
| Eval corpus README | `data/eval/README.md` |
| CHUNKING_SPEC | `contracts/foundation/CHUNKING_SPEC.md` |
| Qdrant collection | `config/qdrant.collection.yaml` |
| Agent CLI | `src/knowledgenexus/presentation/cli/agent/` |
| Eval package | `src/knowledgenexus/eval/` |

---

## How to use this file

1. Assign **Owner** + change **Status** in the top table.  
2. Tick checklists in each step; record PR/label in Notes.  
3. Every `kn-eval` run, add a row to **Update log** + paste the 2 latest-vs-previous lines from `LEADERBOARD.md` into the PR.  
4. Do not jump to step 4 before the gate passes; do not touch step 6 early.
