# START HERE — AI Knowledge Platform context pack (as of 2026-07-08)

This bundle is the complete authoritative state of the **AI Knowledge Platform — Part 1 (Knowledge Foundation)** project, ready to load into a new conversation. Read this file first, then the contracts in the order below.

## What this project is

Part 1 crawls, normalizes, and exports knowledge from **Confluence (space SVMC)** and **Git (`spen-sdk`)** into validated JSONL export snapshots for a downstream RAG system. Part 1 owns: connectors, raw store, normalization, chunking, ACL, relations, symbols, media, export. **Part 1 does NOT do embedding / Qdrant / retrieval / chat** — Part 2/3 are implemented as **sibling bounded contexts inside the same KnowledgeNexus product repository**: Indexing, Retrieval, Chat, and Presentation, which consume Part 1's export snapshot. The project is at the **spec/planning stage**: contracts are being finalized; no production export or crawl has run yet.

## Read order (priority)

1. `schemas/*.json` — the data contract; **wins all field-level disputes**. Start with `defs.schema.json` (ID grammars + enums, referenced by the rest), then the record schemas, then `manifest.schema.json`.
2. `CHUNKING_SPEC.md` — chunking behavior & token budget. §1 now locks BGE-M3 and `chunker_version 1.2.0`; the active medium budget remains provisional until benchmark evidence exists.
3. `decision_logs/AI_Knowledge_Platform_Master_Spec_v7_1.md` — architecture, policies, scope (the normative base).
4. `decision_logs/AI_Knowledge_Platform_v7_2_Update.md` — export layout, storage roles, verbatim embedding, ACL repo tag (D1–D7).
5. `decision_logs/AI_Knowledge_Platform_v7_3_Update.md` — bge-m3 direction, benchmark plan (D8–D13).
6. `decision_logs/AI_Knowledge_Platform_v7_4_Update.md` — POC source binding, dataset, Jira, bge-m3 lock, scope classifier, media policy, D22 consumer pointer (D14–D22).
7. `decision_logs/AI_Knowledge_Platform_v7_5_Update.md` — single-repo modular-monolith layout + Clean Architecture bounded-context dependency rules (D23–D35).
8. `Task2_Task3_Integration_Contract.md` — the consumer contract KnowledgeNexus implements against (10 hard constraints + mapping + roadmap).

Precedence (highest wins): `schemas/` → `CHUNKING_SPEC` → v7.1 → v7.2 → v7.3 → v7.4 → v7.5 → integration contract. `AI_Knowledge_Platform_Master_Spec_v7.md` is a **historical baseline** (audit/diff only). `reference/` holds the other team's KnowledgeNexus plan and the project README — context, not normative.

## Locked decisions (quick reference)

- **Sources:** Confluence SVMC / root page `938880621` (SPenSRV); Git repo **`spen-sdk`** (hyphenated, canonical), branch `develop`, one branch only (identity constraint). HQ wiki SPENSDK/`271852384` deferred to Phase 1.1.
- **Dataset:** one unified corpus `spen_knowledge_poc`, versioned snapshots under `data/exports/<name>/<version>/` + `LATEST.txt`.
- **Jira:** regex-only, extract broad by pattern, allowlist `SVMCSPEN` for RelationRecords; PAT deferred.
- **Embedding/chunking:** **bge-m3, 1024-dim, `chunker_version 1.2.0`** (confirmed). Initial budget = `medium` (450/1000/64), **provisional** (`profile_status` in `embedding_profile.yaml`, not in the version string; manifest uses `config_hash` for change detection). Winner chosen after a 2-round benchmark; code stays on symbol boundaries; `ChunkRecord.text` embedded verbatim.
- **Scope classifier:** advisory rule-based only; page-tree (`include_roots`/`exclude_subtrees` by page_id, human-approved) is the exclusion authority; `page_relevance`/`media_policy` split; `pending_review` = include text / metadata_only media; weights provisional (calibrate after real inventory); 6 reclassify triggers; `moved_out_of_scope` tombstone in delta.
- **Media:** metadata-first; draw.io parse-source-first; tables as source-of-truth; PDF text-first; chart images OCR-labels-only (no numeric fabrication); MVP emits **no** `attachment_text` chunks (media stays in `media_assets.jsonl`); MediaAsset inherits parent ACL.
- **Consumer (KnowledgeNexus):** reads export snapshot only; validates before import; embeds verbatim; Qdrant `point_id = uuidv5(NS, chunk_id)`; `acl_tags` in payload + enforced deny-safe before results/chat; tombstones applied to hydrate DB + Qdrant branched by `entity_type`; adds tables/ports for relations/acl/symbols/media; does not re-parse POC sources; adds `GIT` source type.
- **Repository model (v7.5, corrected):** KnowledgeNexus and the AI Knowledge Platform are **one product / one repo** (modular monolith), not separate products. Foundation, Indexing, Retrieval, Chat, Presentation are **bounded contexts** under vertical Clean Architecture. Boundary = `contracts/foundation` + `data/exports` + importer adapter + **CI import rules** (import-linter): indexing↛foundation, retrieval/chat↛indexing.infrastructure, only foundation reads `data/raw`/`data/work`, Qdrant holds slim payload (no full text). Separate repos are a secondary deployment option only.

## Open items (operational, not design)

`data_root` + disk cap (before full media crawl) · real PAT values (at code time) · real `exclude_subtrees` (after inventory) · winning bge-m3 budget (after benchmark) · fill 37-item benchmark anchors from crawled corpus · enable HQ wiki (Phase 1.1) · multi-branch (post-MVP, needs identity change) · query-time ACL resolver owner · Task 3 retrieval design doc · import-linter ruleset + sample_export fixture owner (v7.5). The v7.4 Part B BGE-M3 contract migration and active `spen-sdk`→`spen-sdk` spelling correction are applied; historical decision-log text remains unchanged for audit fidelity.

## Working norms (please continue these)

- **Multi-AI cross-validation:** decisions are drafted across tools (e.g. ChatGPT in parallel), then brought here to evaluate **against the actual schemas/spec** (verify enums/fields from the files, don't trust memory), then consolidated into the versioned decision logs. This is a deliberate quality gate.
- **Analyze before editing:** comment/critique without modifying files unless explicitly told to. File creation/edits are a separate, deliberate step.
- **Never silently amend contracts:** schema/CHUNKING_SPEC changes are raised as explicit patch items (v7.x Part B), not made quietly.
- **Layered decision logs, not rewrites:** keep stacking v7.x updates on Master v7.1. v8 is reserved for a post-POC consolidation or a genuinely breaking change (see v7.5 Part B).

## Suggested next steps (two clean entry points)

1. **Implement M6D against the migrated contract** — use the explicit external BGE-M3 tokenizer bundle and the injected immutable active profile; do not tune the provisional budget from a single page.
2. **Complete the later retrieval benchmark** — compare profiles only after representative corpus anchors exist, then record any accepted configuration migration explicitly.
