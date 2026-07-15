# Task2_Task3_Integration_Contract.md

| Field | Value |
|---|---|
| Status | Integration Contract (normative for the Part 1 → Part 2/3 handoff) |
| Date | 2026-07-08 |
| Governs | The boundary between Part 1 (AI Knowledge Platform / Knowledge Foundation) and Part 2/3 (KnowledgeNexus: indexer, hydrate store, Qdrant, retrieval API, Gauss chat). |
| Consumes | `schemas/` · `manifest.json` · the export snapshot layout (v7.2 D1) · `AI_Knowledge_Platform_v7_4_Update.md` D22 |
| Audience | KnowledgeNexus implementers (M0–M6) and Part 1 export owners. |
| Precedence | This contract sits **below** `schemas/` — it consumes them and must not amend them. Where a constraint here would require a schema change, that change is raised as a schemas patch first, not made silently. Order: `schemas/` → `CHUNKING_SPEC.md` → Master v7.1 → v7.2 → v7.3 → v7.4 → **this contract**. |

## Purpose

Part 1 and KnowledgeNexus are philosophically aligned — both use hybrid storage (relational text+metadata, vector store for embeddings), both treat the vector store as non-authoritative, both target bge-m3 1024-dim, and both re-sync via delete-then-upsert on a source key. This contract closes the concrete gaps so the two systems interoperate without losing Part 1's provenance, ACL, relations, symbols, or tombstone semantics.

The core rule: **for POC sources Part 1 owns, KnowledgeNexus consumes the export snapshot; it does not re-parse or re-chunk those sources.** KnowledgeNexus's own parser/chunker path remains valid only for sources Part 1 does not export.

## Boundary

```
Part 1 (AKP)
  produces →  data/exports/<dataset_name>/<dataset_version>/   (versioned snapshot; LATEST.txt)
                    │  (read-only; raw/ and work/ are NOT exposed)
                    ▼
Part 2 (KnowledgeNexus Indexer)
  validate → import → embed verbatim → index (SQLite + Qdrant, deny-safe ACL)
                    ▼
Part 3 (KnowledgeNexus Retrieval / Chat)
  Qdrant search → SQLite hydrate → ACL enforce → Gauss answer with citations
```

---

# Section 1 — Consumer input (the export snapshot)

KnowledgeNexus reads exactly the versioned snapshot directory and nothing else from Part 1:

- Resolve the snapshot: read `LATEST.txt` for the current `dataset_version`, or take an explicit version. Path: `data/exports/<dataset_name>/<dataset_version>/`.
- Files consumed: `manifest.json`, `documents.jsonl`, `chunks.jsonl`, `relations.jsonl`, `acl.jsonl`, `media_assets.jsonl`, `symbols.jsonl`, `tombstones.jsonl`. `quality_report.md` is human reference, **not** imported. `sync_state.jsonl` is present in the export (Part 1 output contract) but is **optional diagnostic input** — KnowledgeNexus may ignore it; it is Part 1 crawl-state, not consumer data.
- `manifest.dataset_version` MUST equal the folder name; mismatch aborts the import.
- The ingest job records which `dataset_name`/`dataset_version` it consumed, for traceability and idempotent re-runs.

---

# Section 2 — Hard constraints (normative)

These are the conditions under which the handoff is correct. Each is testable.

### C1 — Snapshot-only input
Part 2 reads **only** the export snapshot. It MUST NOT read Part 1's `data/raw/` or any `data/work/` directory (e.g. `scope_decisions.jsonl`, `media_extraction_details.jsonl`). Those are Part 1-internal (v7.2 D1). Any need for data not present in the export is a gap to fix in the export, not a reason to reach into Part 1 internals.

### C2 — Validate before import
Before importing any record, validate `manifest.json` and **every** JSONL record against its schema in `schemas/`. Reject the snapshot on any validation failure — do not import partial/invalid data. `schema_version` on each record must be recognized; unknown major versions abort.

### C3 — Embed verbatim
`ChunkRecord.text` is embedded **exactly as delivered**. KnowledgeNexus MUST NOT re-chunk, prepend, append, trim, summarize, translate, or otherwise modify the text before embedding. The text was normalized and hashed into `chunk_id` upstream; any mutation breaks provenance and the skip-re-embed logic. Noise reduction happens at retrieval/rerank time, never by altering chunk text.

### C4 — Deterministic Qdrant point IDs
Qdrant point IDs must be reproducible from `chunk_id`. Part 1 `chunk_id` is a string (`chunk:confluence:{hex16}` / `chunk:git:…`), which is **not** a valid Qdrant point ID (Qdrant accepts only unsigned integers or UUIDs). Therefore:

```
point_id = uuidv5(POINT_ID_NAMESPACE, chunk_id)
```

- `POINT_ID_NAMESPACE` is a single fixed UUID constant, pinned in KnowledgeNexus config and never changed (changing it orphans every existing point). Agree on one value at M0 and record it here.
- The original `chunk_id` string MUST be stored in the Qdrant payload (C5) and as the SQLite chunk primary key, so hydrate and tombstone deletion can round-trip `point_id ↔ chunk_id`.

### C5 — ACL, filter, and provenance fields in the payload
The Qdrant slim payload MUST include `acl_tags` and the filter fields required to serve queries — at minimum: `chunk_id`, `document_id`, `source_system`, `source_type`, `content_kind`, `language`, `acl_tags`, plus the source-specific filters `page_id`, `space_key` (Confluence) and `repo`, `branch`, `file_path`, `symbol` (git), and a recency field (`source_version`/`updated_at`). `acl_tags` is **not** optional and **not** SQLite-only — ACL must be filterable at (or before) the vector-search boundary. Full `text`/`content`, `title`, `heading_path`, and the remainder stay SQLite-only and are hydrated after search.

**Snapshot provenance** MUST also be attached to every imported chunk (payload and/or hydrate DB): `dataset_name`, `dataset_version`, `chunker_version`, `embedding_model`, and `config_hash`. Note `dataset_version`/`dataset_name`/`config_hash`/`embedding_model` are **stamped by Part 2 from the manifest context at import time** (they are not per-chunk fields in the export), while `chunker_version` is present on each `ChunkRecord`. This enables audit ("which snapshot did this answer come from"), stale-sweep (for a `full_snapshot` replace, delete points whose `dataset_version` ≠ the new one as a safety net), and rollback.

### C6 — Enforce ACL before returning anything
Retrieval and chat MUST enforce `acl_tags` **deny-safely** before results reach the user or the LLM prompt:

- Resolve the caller identity to a set of granted principals (`user:…`, `group:…`, `space:…`, `repo:…`).
- A chunk is visible only if its `acl_tags` intersect the caller's principals (OR-semantics, as defined by the ACL grammar).
- Deny-safe default: if the caller's principals cannot be resolved, or a chunk carries `restricted:unresolved`, the chunk is **excluded**. Never fail open.
- Enforcement happens after hydrate and **before** the result set is returned or fed to Gauss — never rely on the LLM to withhold restricted content.
- The query-time identity→principals resolver is a required component (owner tracked in Open Questions); the vector store and hydrate DB are **not** the ACL authority (v7.2 D2).

### C7 — Apply tombstones to both stores, branching by entity type
On a `delta` snapshot, process `tombstones.jsonl` so removed content disappears from **both** SQLite and Qdrant. Apply tombstones **before or atomically with** the upserts in the same snapshot, so stale rows/vectors never linger or resurface in retrieval.

Each `TombstoneRecord` carries `entity_type`, `entity_id`, and `reason`. Behavior is **branched by `entity_type`** — do not blanket-delete chunks for every tombstone (a relation tombstone must not delete chunks):

| `entity_type` | Action |
|---|---|
| `document` | Delete the document + all its chunks (SQLite rows **and** Qdrant points via `uuidv5(NS, chunk_id)`) + its media/relations/acl rows. |
| `chunk` | Delete that one chunk row and its Qdrant point only. |
| `relation` | Delete the relation row only. |
| `acl` | Delete/update the acl row; re-evaluate affected chunks — if their ACL becomes unresolved, hide them (deny-safe, C6). |
| `media` | Delete the media_asset row only. |
| `symbol` | Delete the symbol row (and its exact-lookup index entry) only. |

The valid `reason` values are exactly `source_deleted`, `access_revoked`, `moved_out_of_scope`, `content_updated`, `config_invalidated` (per `defs.schema.json#/$defs/tombstoneReason`) — all result in removal/invalidation of the referenced entity; `reason` is provenance/audit, `entity_type` drives the action.

### C7a — config_hash is index-invalidating
Part 2 MUST treat a change in `manifest.config_hash` (or, once present, an explicit profile identity per v7.4 Part B item 5) as **index-invalidating for the affected `full_snapshot`**: re-embed and re-index rather than assuming existing vectors are still valid. Because a budget/config change can occur without a `chunker_version` change (v7.4 D17), `chunker_version` alone is **not** sufficient to detect that chunking config changed — `config_hash` is the authoritative signal.

### C8 — Add storage for the record types KnowledgeNexus lacks
The current KnowledgeNexus model (documents, chunks, ingest_jobs) cannot represent the full export. Add tables and ports for:

- **relations** — from `relations.jsonl` (e.g. `mentions_jira_key`, `embeds_media`). New `RelationRepositoryPort` + table.
- **acl** — from `acl.jsonl`, feeding the C6 enforcement path. New `AclRepositoryPort` (and the identity→principals `AclResolverPort`).
- **symbols** — from `symbols.jsonl`, with an **exact-lookup index** (symbol name/qualified-name → chunk/document) so code identifier queries resolve by lookup, not only by vector similarity. New `SymbolRepositoryPort` + table + index.
- **media_assets** — from `media_assets.jsonl` (`extracted_text`, `summary`, `confidence`, `processing_status`, `raw_uri`). New `MediaRepositoryPort` + table. Media inherits parent-document ACL (v7.4 D21).
- **tombstones** — a driver that applies C7, not necessarily a long-lived table.

These may be SQLite (M1) now and PostgreSQL (M6) later; the tables/ports must exist regardless of backend.

### C9 — Do not re-parse Part 1 POC sources
KnowledgeNexus's `ConfluenceParser` and `RecursiveChunker` (plan M2) and the direct "Confluence → SQLite + Qdrant" ingest path (plan M3) **do not apply** to POC sources exported by Part 1. For those sources, ingestion is an `ExportSnapshotReader` that consumes pre-built chunks. The KnowledgeNexus parser/chunker path is retained **only** for sources Part 1 does not export (future non-POC sources). This prevents divergent chunk boundaries, non-deterministic IDs, and loss of ACL/relations/symbols that direct re-parsing would cause.

### C10 — bge-m3 alignment, chunking follows v7.4
Part 2/3 use **bge-m3, 1024-dim** (matches Part 1). But for Part 1 sources:

- Chunks arrive **pre-chunked**; KnowledgeNexus does not set its own chunk budget for them (no `1500 chars / 150 overlap` applied to Part 1 chunks). `chunker_version` (`1.2.0`) and the profile come from Part 1 (v7.4 D17) and are read from the manifest/records, not chosen by KnowledgeNexus.
- The Qdrant collection MUST be a fresh **1024-dim** collection. Never reuse a 384-dim (MiniLM-era) collection. The collection name should encode model+dim to prevent accidental reuse (see Open Questions).
- Token counting for any KnowledgeNexus-owned (non-Part-1) chunking uses the bge-m3 tokenizer, consistent with v7.4.

---

# Section 3 — Record → KnowledgeNexus storage mapping

| Part 1 export record | KnowledgeNexus storage | Notes |
|---|---|---|
| `CanonicalDocument` (`documents.jsonl`) | `documents` table | Map `document_id`/stable key → `documents.id`; `page_id` or `repo:file_path` → `source_id`; `source_system` → source type (needs `GIT`, see below); page/repo metadata → `documents.metadata`. |
| `ChunkRecord` (`chunks.jsonl`) | `chunks` table + Qdrant point | `chunk_id` → `chunks.id` (PK, string) and payload; `text` → `chunks.content` (embedded verbatim); filter fields → core/indexed payload (C5); provenance + rest → `extra`. Point via C4. |
| `RelationRecord` (`relations.jsonl`) | `relations` table (new, C8) | Keyed by `relation_id`; used for graph expansion at retrieval (Task 3). |
| `ACLRecord` (`acl.jsonl`) | `acl` table (new, C8) | Authority for C6 enforcement; `acl_tags` also mirrored into chunk payload (C5). |
| `SymbolRecord` (`symbols.jsonl`) | `symbols` table + exact-lookup index (new, C8) | Enables identifier lookup for code queries. |
| `MediaAsset` (`media_assets.jsonl`) | `media_assets` table (new, C8) | `extracted_text` searchable per policy; ACL inherited from parent document. |
| `TombstoneRecord` (`tombstones.jsonl`) | delete/invalidate driver (C7) | Removes from SQLite + Qdrant; not a long-lived table. |
| `manifest.json` | ingest-job metadata | Records `dataset_name`/`dataset_version`, `export_mode` (`full_snapshot`/`delta`), counts. |
| `quality_report.md` | — | Human reference; not imported. |

**SourceType gap:** KnowledgeNexus's enum `CONFLUENCE | MCP | URL | FILE` has no value for code. Add a `GIT` (or `CODE`) source type so git/symbol chunks are representable. Note also that KnowledgeNexus overloads "source_type" for the *system*, whereas Part 1 separates three axes: `source_system` (`confluence` / `git`), `source_type` (the source-artifact kind: `wiki_page` / `code_file` / `attachment_text`), and `content_kind` (the content kind: `prose` / `table` / `code_block` / `code_symbol` / `code_window`). Map Part 1 `source_system` → KnowledgeNexus source type, and carry both `source_type` and `content_kind` into the indexed payload for filtering.

**Field placement (ChunkRecord → KnowledgeNexus chunk):**
- **Indexed payload (Qdrant, C5):** `chunk_id`, `document_id`, `source_system`, `source_type`, `content_kind`, `language`, `acl_tags`, `page_id`, `space_key`, `repo`, `branch`, `file_path`, `symbol`, `source_version`/`updated_at`.
- **SQLite only (hydrate):** `text`→`content`, `title`, breadcrumb/heading path, `relation_ids`, `content_hash`, `chunker_version`, `token_count`, and anything else → `extra`.
- **Promotion rule:** a field moves from `extra` into indexed/core only if it is filtered frequently at query time (consistent with KnowledgeNexus's own "promote from extra to core" rule).

---

# Section 4 — KnowledgeNexus roadmap adaptation

The KnowledgeNexus milestones stay largely intact; the ingestion path is what changes for POC sources.

| Milestone | Change |
|---|---|
| **M0 Foundation** | Add `source_metadata` for the AKP export; add ports for relations/acl/symbols/media (C8); pin `POINT_ID_NAMESPACE` (C4); add `GIT` source type. |
| **M1 Core Storage** | Keep SQLite + Qdrant slim adapter, but extend payload to include `acl_tags` + filter fields (C5); add tables for relations/acl/symbols/media (C8); Qdrant collection is 1024-dim (C10). |
| **M2 Ingestion** | **Replace** the Confluence-parser/RecursiveChunker path with an `ExportSnapshotReader` for POC sources (C9). Keep `BgeM3Embedder`, but it embeds `ChunkRecord.text` verbatim (C3). The 1500-char chunker applies only to non-Part-1 sources. |
| **M3 Integration (MVP-1)** | E2E becomes: read snapshot → validate (C2) → apply tombstones (C7) → upsert SQLite + Qdrant with deterministic point IDs (C4) and ACL payload (C5). Idempotent re-sync keyed on `chunk_id`/`document_id` from the snapshot. |
| **M4 Retrieval (MVP-2)** | Qdrant search → SQLite hydrate → **ACL enforcement (C6)** before returning. Add symbol exact-lookup and (Task 3) relation expansion. |
| **M5 Chat (MVP-3)** | Gauss RAG over ACL-filtered results only (C6); citations carry Part 1 provenance (see Open Questions for the citation shape). |
| **M6 Production** | PostgreSQL migration must preserve the relations/acl/symbols/media tables and ACL enforcement; object storage may hold raw binaries but is still not the ACL authority. |

---

# Section 5 — Repository and module integration

Folder / module layout and dependency direction are governed by **`AI_Knowledge_Platform_v7_5_Update.md`** (the layout authority); this section states only what the consumer side must do. The full trees are in v7.5 and are not duplicated here.

- **Single product repository (preferred, v7.5 D23).** KnowledgeNexus **is the product repo**. Foundation, Indexing, Retrieval, Chat, and Presentation are **bounded contexts / modules inside it**, not separate products. The Part 1 ↔ Part 2/3 boundary is an **in-repo module boundary**, enforced by dependency rules and CI import checks (v7.5 D34), not by repository separation. Indexing/Retrieval/Chat still do **not** import Foundation Python modules — they consume the export snapshot via the importer adapter.
- **Contracts are a single in-repo location:** `contracts/foundation/` (`schemas/`, `CHUNKING_SPEC.md`, `embedding_profile.yaml`, the v7.4/v7.5 logs, this contract). Foundation validates against it before writing the export; Indexing validates against the same copy before importing (shared validator, v7.5 D31). No second/vendored copy. Indexing still asserts `manifest.schemas_version` matches at import time and aborts on mismatch.
- **Components to add (v7.5 D24/D31):**
  - `shared/contracts/foundation/contract_loader.py` and `shared/contracts/foundation/schema_validator.py` — the shared validator used by both Foundation (pre-export) and Indexing (pre-import).
  - `indexing/infrastructure/importers/` — the export-snapshot reader (streams the JSONL files).
  - `indexing/application/use_cases/import_akp_snapshot.py` — orchestrates resolve → validate (C2) → tombstone (C7) → upsert (C4/C5), exposed via `presentation/api/v1/import_snapshot.py`.
- **Runtime configuration boundary (v7.5 D27):**

```
AKP_CONTRACT_ROOT=./contracts/foundation
AKP_EXPORT_ROOT=./data/exports
AKP_DATASET_NAME=spen_knowledge_poc
AKP_USE_LATEST=true
AKP_DATASET_VERSION=<optional explicit version>
```

Resolution: if `AKP_USE_LATEST=true`, read `${AKP_EXPORT_ROOT}/${AKP_DATASET_NAME}/LATEST.txt`; resolve `${AKP_EXPORT_ROOT}/${AKP_DATASET_NAME}/${dataset_version}`; validate `manifest.dataset_version == dataset_version`; validate JSONL against `${AKP_CONTRACT_ROOT}/schemas`; import. `AKP_EXPORT_ROOT` points at `data/exports/` only — `data/raw/` and `data/work/` are never referenced (C1).
- **Storage/read-port boundary (v7.5 D29):** Indexing owns `repositories/`, `database/`, `vector_store/`; Retrieval reads through Indexing **read ports** only and must not import `indexing.infrastructure`. Chat must not touch Qdrant/SQL directly.
- **Separate repositories** remain a **secondary deployment option** only; if ever used, the same import prohibitions and the `data/exports`-only rule still hold.

---

# Open questions (integration)

- **`POINT_ID_NAMESPACE` value** — pick one fixed UUID at M0 and record it here; never change it afterward.
- **Qdrant collection name for bge-m3** — encode model+dim to prevent 384-dim reuse, e.g. `spen_knowledge_poc__bge_m3__1024`. Confirm the convention.
- **SQLite → PostgreSQL timing** — KnowledgeNexus plans SQLite → PostgreSQL later; fine, provided the relations/acl/symbols/media tables and C6 enforcement exist in both.
- **Query-time ACL resolver owner** — the identity→principals resolver (incl. `repo:spen-sdk` → GitHub Enterprise team membership) is required for multi-user C6 and is currently unowned (mirrors v7.4 open question). Not blocking for a single-user PAT POC, but blocking before multi-user.
- **Retrieval benchmark ownership** — Part 1 supplies the corpus and real anchors for the 37-item template; who runs Round 1 (dense sweep) / Round 2 (hybrid) and stamps the winning bge-m3 profile back into CHUNKING_SPEC §1 + `chunker_version 1.2.0`?
- **API citation shape** — define the fields a Part 3 chat citation returns: at least `title`, `url`/`page_id` or `repo:file_path`, `chunk_id`, and `source_version`, so answers are traceable to a specific snapshot version.
- **dataset handshake** — confirm the importer resolves the snapshot via `LATEST.txt` and records the consumed `dataset_version` in the ingest job (Section 1).
- **Export transport** — in local single-repo development, `AKP_EXPORT_ROOT` resolves to `./data/exports`. For remote/dev-server deployment, decide whether snapshots are exchanged by shared mount, artifact download, or object storage. No second copy of `contracts/foundation` is introduced.
