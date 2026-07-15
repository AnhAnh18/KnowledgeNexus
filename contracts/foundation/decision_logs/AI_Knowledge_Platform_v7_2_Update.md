# AI_Knowledge_Platform_v7_2_Update.md

| Field | Value |
|---|---|
| Status | Update / Decision Log (normative where stated) |
| Based on | AI_Knowledge_Platform_Master_Spec_v7_1.md · CHUNKING_SPEC.md (chunker_version 1.1.0) · schemas/ |
| Date | 2026-07-03 |
| Purpose | Capture the architectural decisions agreed after the Part 2 / vector-storage discussion. This file layers decisions on v7.1 — it does not rewrite the master spec, and it never restates normative numbers that live in CHUNKING_SPEC.md or schemas/ (it references them). |

## Changelog (v7.1 → v7.2)

| # | Area | Change |
|---|---|---|
| 1 | Chunk budget | `overlap_tokens` finalized at 40 (see CHUNKING_SPEC §1). Applied in place to CHUNKING_SPEC §1 and master §16.3 / §20.3. No export ever existed with the previous draft value, so there was no compatibility surface: `chunker_version` stays 1.1.0 and no `config_invalidated` cycle was needed. |
| 2 | ACL grammar | `repo:{name}` tag added for git-source chunks (D4). `schemas/defs.schema.json` pattern widened and master §14.1 updated, in place within schema_version 1.0 (pre-release). |
| 3 | Export layout | Versioned snapshot directories; Part 2 reads exports only (D1). |
| 4 | Part 2 storage | Qdrant + PostgreSQL + file-store roles recorded; neither is source of truth nor ACL authority (D2). |
| 5 | Embedding | Model, dimension, collection, and the verbatim-text rule recorded (D3). |
| 6 | Expansion model | Multi-source expansion checklist; unification only at the chunk/vector layer (D5). |
| 7 | Module Q&A | `module_map.yaml` / `module_summary` direction, post-MVP, with provenance + ACL guard (D6). |
| 8 | Doc set | Normative document set and precedence defined; explainer docs declared non-normative (D7). |

---

## D1. Export versioning and Part 2 handoff

- Part 1 exports versioned snapshots under `data/exports/<dataset_name>/<dataset_version>/`.
- The directory name `<dataset_version>` MUST equal `manifest.dataset_version` inside it.
- A Windows-safe pointer file `LATEST.txt` (containing the current `<dataset_version>` string) marks the current snapshot. No symlinks — unreliable on Windows workstations.
- **Part 2 reads ONLY export snapshots.** `data/raw/` and any working directories are Part 1 internals; reading them from Part 2 is a contract violation.
- POC export mode is `full_snapshot` (master §16.2). `delta` + tombstones are already fully specified and can be enabled later by configuration, not redesign.

## D2. Part 2 storage design (owned by Part 2 — recorded here for context)

- **Qdrant** — collection `akp_chunks_v1`: vectors + compact payload for filtering. The point ID MUST be derived deterministically from `chunk_id` (e.g. UUIDv5 over the `chunk_id` string) so that upsert and skip-re-embed semantics keyed by `chunk_id` (CHUNKING_SPEC §3, §7) carry through to the vector store.
- **PostgreSQL** — full chunk text, document metadata, relations, ACL records, symbols, media metadata, dataset-version bookkeeping, and the `chunk_id` ↔ Qdrant-point mapping.
- **File/object store** — exported artifacts (and originals where needed).
- Neither Qdrant nor PostgreSQL is the source of truth, and **neither is the ACL authority**. Authority = the Part 1 export contract and the source systems behind it.
- POC exposure rule restated from master §14.4: the dataset is crawled with a personal PAT, so it MUST NOT be served to any user other than the PAT owner. This applies equally to PostgreSQL and Qdrant access paths.

## D3. Embedding model and chunk consumption

- Model: `sentence-transformers/all-MiniLM-L6-v2`, output dimension **384**. The model-fit caveats (English-only; not code-trained) stand as recorded in CHUNKING_SPEC §1 and master §20.3.
- Qdrant collection: `akp_chunks_v1` (384-dim).
- **`ChunkRecord.text` is embedded verbatim (normative).** Part 2 MUST NOT summarize, prepend, trim, or otherwise modify it before embedding. `chunk_id` is a hash over that text (CHUNKING_SPEC §3): modifying the text silently breaks re-embed skipping and provenance. Any useful prefixing (heading breadcrumb, file/symbol path) is already inside `text` by construction (CHUNKING_SPEC §4.2, §5.2).
- Chunk budget: defined solely in CHUNKING_SPEC.md §1 (chunker_version 1.1.0). Deliberately not restated here — one living copy of the numbers.

## D4. ACL for multi-source

- The `acl_tag` grammar gains `repo:{name}` — "every user with read access to the repository", the git analogue of `space:{KEY}`. POC git chunks carry exactly `["repo:spensdk"]`. Part 1 does not enumerate repo members; mapping caller identity → repo read access is query-time-resolver territory, the same boundary as group membership (master §14.4).
- Every future source (PLM, Figma, other wikis) requires a **deny-safe ACL mapping per master §14.2 before its chunks are exported**. No trustworthy mapping → `["restricted:unresolved"]` (default deny), never a permissive guess.

## D5. Multi-source expansion model

- Raw data stays separate per source. Unification happens only at the ChunkRecord / vector-collection layer. "One searchable index" ≠ "one mixed text blob": `source_system`, `source_type`, `document_id`, provenance fields, `relation_ids`, and `acl_tags` preserve origin on every record.
- Checklist per new source (PLM issues, Figma, Markdown repos, additional wikis):
  1. Connector + raw-store path + normalizer to CanonicalDocument / ChunkRecord / MediaAsset.
  2. Enum additions (`source_system`, `source_type`, `content_kind`, `relation_type`) — additive, minor schema bump; every export ships its schema set (`manifest.schemas_version`), so consumers never guess.
  3. Deny-safe ACL mapping (D4) — blocking prerequisite, not a follow-up.
  4. Relation-extraction rules (IDs/URLs cross-linking to Jira/Confluence/Git) + quality-report counters.
- Symbol ↔ chunk linkage stays via `SymbolRecord.chunk_id` (master §12.2), not via a RelationRecord type. Explainer documents describing a `defines_symbol` relation should be corrected (see D7).

## D6. Module-level Q&A (post-MVP)

- Phase 1.5: `module_map.yaml` — a deterministic `file_path` → module mapping (folder-based modules such as `worddoc`, `document`, `model`). Adds an optional `module` payload field to ChunkRecord (additive, minor bump).
- `module_summary` chunks are **AI-generated derived content**. If introduced, they MUST carry generated/derived provenance marking and MUST inherit ACL from their member files deny-safely (most-restrictive combination, per the §14.2 invariant). This directly mitigates the master §20.1 risk "AI-generated docs become unverified truth".

## D7. Normative document set and precedence

The normative contract, in precedence order (highest wins):

1. `schemas/` — record shapes; always wins on any field-level disagreement.
2. `CHUNKING_SPEC.md` — chunking behavior and budget.
3. `AI_Knowledge_Platform_Master_Spec_v7_1.md` — architecture, policies, scope.
4. This file — decisions layered on v7.1.

`AI_Knowledge_Platform_Master_Spec_v7.md` (faithful regeneration) is the historical baseline, kept for audit/diff only. Explainer documents — e.g. `NORMALIZE.md`, `JSONL_OUTPUT_RELATIONSHIP.md`, wiki explainer pages — are **non-normative**: where they disagree with the set above, the set above wins and the explainer must be corrected. Agent/working context = items 1–4; the v7 baseline and explainers may be omitted from agent context.

## Open questions

- Part 2 PostgreSQL schema design document: owner and timing (Part 2 side; Part 1 needs only the contract already defined).
- `module_map.yaml` Phase 1.5: timing, owner, and the initial folder → module table proposal.
- PLM / Figma / additional wiki sources: roadmap confirmation; reserve enum values once confirmed.
- Query-time resolver: who maps caller identity → repo read access (GitHub Enterprise teams?) — same open boundary as group-membership resolution (master §14.4).
- `<dataset_name>` naming convention for the exports directory (e.g. `svmc_spensdk_poc`).
- Carried open questions from master §20.3 remain: branch choice, exclude subtrees, official Jira keys, disk cap, Task 2 validation owner.
