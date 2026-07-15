# AI_Knowledge_Platform_v7_3_Update.md

| Field | Value |
|---|---|
| Status | Decision Log / Migration Plan |
| Date | 2026-07-06 |
| Based on | AI_Knowledge_Platform_v7_2_Update.md · CHUNKING_SPEC.md (chunker_version 1.1.0, still normative) · schemas/ |
| Purpose | Record the migration from `all-MiniLM-L6-v2` to `BAAI/bge-m3` for POC embedding, the benchmark gate that must pass before any bge-m3 chunk budget becomes normative, and the non-normative provisional profiles used for that benchmark. |

**Migration invariant.** This is a *plan*, not a promotion. Until a benchmark selects a winning profile and it is stamped into CHUNKING_SPEC.md §1 as `chunker_version` 1.2.0, the last locked normative chunking profile remains all-MiniLM-L6-v2 (200 / 240 / 40, chunker_version 1.1.0). Every bge-m3 number in this document and in `embedding_profile.yaml` is **provisional**.

## Changelog (v7.2 → v7.3)

| # | Area | Change |
|---|---|---|
| 1 | Embedding model | Migration decision to `BAAI/bge-m3` recorded (D8). Not yet promoted into the normative chunking profile. |
| 2 | Chunk budget | Benchmark gate defined; `chunker_version` 1.2.0 reserved for the winner (D9). CHUNKING_SPEC §1 unchanged. |
| 3 | Benchmark method | Two-round, one-variable-at-a-time methodology (D10). |
| 4 | Git history | Explicitly post-MVP; MVP stays snapshot + symbol + commit_hash (D11). |
| 5 | Relation vocabulary | MVP enum stays minimal; symbol↔chunk via `SymbolRecord.chunk_id`; `references_file` reserved MVP+ only (D12). |
| 6 | Retrieval | Task 3 retrieval design is a separate document; hybrid + exact lookup + rerank + relation expansion; no hard Confluence-first fallback (D13). |
| 7 | CHUNKING_SPEC | Typo fix overlap `(75)` → `(40)` in §4.4; migration note added (§0.1). No budget/version change. |
| 8 | Schema | `chunk_record.schema.json` `token_count` description made model-agnostic. No shape/required/version change. |

---

## D8. Embedding model migration to BAAI/bge-m3

- Primary POC embedding candidate: **`BAAI/bge-m3`**.
- Provider: local / open-weight / self-host (free). Runs under sentence-transformers / FlagEmbedding.
- `vector_dim`: **1024**.
- Tokenizer: **SentencePiece, XLM-RoBERTa-based** — not the BERT WordPiece of MiniLM, not `tiktoken`. This is why token counts must be measured with the configured model's own tokenizer (CHUNKING_SPEC §1), and why the schema description stays model-agnostic (D-schema below).
- Retrieval capabilities: **dense, sparse, ColBERT** in one model. The *capability* is recorded here; **the retrieval-mode implementation belongs to Task 2 / Task 3**, not Part 1.
- **Qdrant:** the existing MiniLM 384-dim collection must **not** be reused. Task 2 recreates or provisions a separate 1024-dim collection/config for bge-m3. Vector dimension is a hard incompatibility, not a config tweak.
- Model-fit rationale: bge-m3 is multilingual (100+ languages, 170+ in training) with an 8192-token context and built-in sparse matching — a better fit than MiniLM for this corpus (Korean/Vietnamese/English wiki + code, long design docs, many exact identifiers). Retrieval quality on the actual corpus is still to be confirmed by benchmark, not assumed.

## D9. Chunk budget benchmark gate

- The bge-m3 chunk budget is **not normative yet**. `chunker_version` **1.2.0 is reserved** for the winning bge-m3 profile.
- Until the benchmark finishes, **CHUNKING_SPEC.md §1 remains the last locked normative baseline** (all-MiniLM-L6-v2, 200 / 240 / 40, chunker_version 1.1.0). CHUNKING_SPEC §0.1 carries the migration note pointing here.
- Promotion procedure: pick the winning profile → write its numbers into CHUNKING_SPEC §1 → bump `chunker_version` to 1.2.0 → this changes chunker config, so it triggers `config_invalidated` → a fresh `full_snapshot` and full re-embed/re-index.
- Task 2 impact: if chunking and embedding are config-driven (budget + model read from `embedding_profile.yaml`, not hard-coded), a budget change should require **no code change** in Task 2 — only a re-run. This is the reason for the profile file.
- Provisional profiles live in `embedding_profile.yaml` (control / small / medium / large). They are benchmark inputs, explicitly labelled provisional, and must never be cited as normative.

## D10. Benchmark methodology

One variable at a time, so results are attributable:

- **Round 1 — dense-only chunk-budget sweep.** Fix retrieval to dense-only. Run the benchmark set across the profiles (control, small, medium, large). Isolate the effect of chunk size. Select the budget that wins on the retrieval metrics.
- **Round 2 — fixed-budget hybrid test.** Keep the Round-1 winning budget fixed. Enable hybrid (dense + sparse, optionally ColBERT) and measure the *added* benefit of sparse/ColBERT over dense-only.
- **Principle:** never change chunk budget and retrieval mode in the same run — a combined change is not attributable.
- The benchmark set (`retrieval_benchmark.template.jsonl`, filled with real anchors) is a **hard dependency**: without it there is no metric to select a winner. Threshold calibration for "not found" (the no-data group) is part of the same benchmark.

## D11. Git history scope

- **MVP** = source code snapshot + tree-sitter symbol index + `commit_hash` of the snapshot. `commit_hash` is stored to trace `source_version` and to validate line ranges only.
- **Post-MVP** = git history / commit / PR ingestion (commit message, author/date, touched files, PR metadata). Questions like "which commit changed this logic?", "who introduced this?", "which PR added this code?" require that ingestion and are **not answerable in MVP**. State this to avoid over-expectation.
- Do **not** add relation types `touched_file` / `changed_by_commit` / `mentioned_in_commit` until the git-history extractor ships. Adding them earlier creates empty vocabulary. When shipped, they enter as additive enum values (minor schema bump) keyed on `commit_hash`.

## D12. Relation vocabulary

- MVP relation enum stays minimal: `mentions_jira_key`, `embeds_media`, `includes_page`, `links_to_page`.
- Symbol ↔ chunk linkage stays via `SymbolRecord.chunk_id` (v7.2 D5) — not a `defines_symbol` relation. This keeps `relations.jsonl` from bloating.
- `references_file` may be reserved as an **optional MVP+** relation **only if** a deterministic extractor exists (e.g. from `#include`, Java `import`, XML references). It is not a blocker and not part of the core MVP.

## D13. Task 3 retrieval design is separate

Retrieval is Task 3 and belongs in its own document (proposed: `Task3_Retrieval_Design.md`), not in the Part 1 spec. Direction recorded so Part 1 exports the right hooks:

- **Hybrid search over all chunks** in one collection + payload filter — not hard source routing. `source_type` / `content_kind` are used to **boost during rerank**, not to gate before search.
- **Exact lookup** alongside vector search when the query contains an identifier: `symbols.jsonl` (qualified_name), Jira key, `file_path`. This is why Part 1 exports `symbols.jsonl` and relation records.
- **Merge → rerank/boost → relation expansion** (via `relation_ids` / `SymbolRecord.chunk_id`) → answer.
- **No hard Confluence-first fallback** in the spec. A single hybrid query over all sources already degrades gracefully; staging, if any, is by rerank/boost, not by re-querying.
- **Source coverage must be exposed**: retrieval returns which `source_type`s were actually retrieved, so the answer layer can state when design/wiki evidence is missing (e.g. "found implementation but no design rationale in the wiki") instead of implying one exists.
- **"Not found" threshold** is relative and benchmark-calibrated (D10), not a hard absolute cosine cutoff; bge-m3 scores are not absolutely calibrated. A useful signal: if both dense and sparse score low, treat as no-answer.

## Schema note (applied in v7.3, no shape change)

`chunk_record.schema.json` `token_count` description changed to model-agnostic: "Token count of `text` measured with the configured embedding model's tokenizer; see CHUNKING_SPEC.md §1 and the active embedding profile." No tokenizer name is hard-coded in the schema. `schema_version`, required fields, and record shape are unchanged.

## Open questions

- Benchmark set content: real anchors (page_id / symbol / Jira key / file_path) to replace the placeholders in `retrieval_benchmark.template.jsonl`. Owner + timing.
- Winning chunk profile + final numbers for `chunker_version` 1.2.0 (decided by Round 1).
- Hybrid value: does sparse/ColBERT beat dense-only enough to justify the extra cost for POC (Round 2)?
- Task 3 retrieval design document: owner + timing.
- Query-time ACL resolver for `repo:{name}` — GitHub Enterprise team vs Gerrit group vs internal IAM. Blocking for multi-user, not for the single-user PAT POC (master §14.4).
- `module_map.yaml` (Phase 1.5): timing and initial folder → module table.
- Carried from v7.2 / master §20.3: spensdk branch choice, exclude subtrees, official Jira keys, disk cap, Task 2 output-validation owner, `<dataset_name>` naming.
