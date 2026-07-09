# AI_Knowledge_Platform_v7_5_Update.md

| Field | Value |
|---|---|
| Status | Decision Log / Update Layer (repository layout + Clean Architecture dependency rules) |
| Date | 2026-07-08 |
| Based on | v7.4 · v7.3 · v7.2 · Master v7.1 · CHUNKING_SPEC · schemas/ · Task2_Task3_Integration_Contract.md |
| Purpose | Define how the Foundation (Part 1) and KnowledgeNexus runtime (Part 2/3) code fit together **inside one product repository**, as bounded contexts under a vertical Clean Architecture, with enforceable dependency rules. This is a **layout + dependency** decision only: no schema change, no `manifest.schema.json` change, no change to Part 1 ownership, and no change to v7.4 consumer-contract semantics. |
| Precedence | `schemas/` → `CHUNKING_SPEC.md` → Master v7.1 → v7.2 → v7.3 → v7.4 → **v7.5** → `Task2_Task3_Integration_Contract.md`. v7.5 governs folder/module layout and dependency direction; the integration contract governs consumer behavior and defers to v7.5 for layout. |

## Correction vs the first v7.5 draft

An earlier framing treated KnowledgeNexus and the AI Knowledge Platform as **separate products in separate repositories**. That is corrected here: they are the **same product / codebase direction**, authored in two parts by two people. The preferred model is therefore a **single product repository (modular monolith)** with vertical bounded contexts — **not** separate repositories. Separate repos are demoted to a secondary deployment option.

## Changelog (v7.4 → v7.5)

- v7.5 defines the **single-repo modular-monolith layout** and the **Clean Architecture dependency rules** between Foundation, Indexing, Retrieval, Chat, and Presentation.
- **No schema change.** `schemas/`, `manifest.schema.json`, `chunk_record.schema.json`, `defs.schema.json`, `CHUNKING_SPEC.md`, and the export snapshot are untouched.
- **No change to Part 1 ownership.** Foundation still owns connectors, raw store, normalization, chunking, ACL, relations, symbols, media, export.
- **No change to v7.4 consumer-contract semantics.** The hard constraints in `Task2_Task3_Integration_Contract.md` are unchanged; v7.5 only says where code lives and which module may depend on which.

## Preserved principles (restated, unchanged)

1. Foundation does **not** do embedding / Qdrant / chat.
2. Indexing / Retrieval / Chat read the export snapshot; they do **not** import Foundation Python modules.
3. `data/raw` and `data/work` are **Foundation-only**; `data/exports` is the boundary.
4. `schemas/` + `CHUNKING_SPEC.md` + the export snapshot are the **official contract boundary**.
5. Consumption is via an **importer/validator adapter** across the module boundary, never by reaching into another context's internals.

---

# Part A — Decisions

## D23. Product repository model

- **Preferred model: single product repository / modular monolith.**
- The repository name can remain **KnowledgeNexus**.
- **AI Knowledge Platform / Foundation is a bounded context inside the product repo**, not a separate product.
- KnowledgeNexus runtime / indexer / API are **sibling bounded contexts** inside the same repo.
- Separate repositories become a **secondary / deployment option** only.
- The boundary is enforced by `contracts/akp`, `data/exports`, **dependency rules (D34)**, and **CI import checks** — not by repository separation.

## D24. Canonical repository layout

This supersedes the earlier separate-repo D24/D25. Canonical layout:

```
KnowledgeNexus/
├── contracts/
│   ├── openapi.yaml
│   └── akp/
│       ├── schemas/
│       ├── CHUNKING_SPEC.md
│       ├── embedding_profile.yaml
│       ├── AI_Knowledge_Platform_v7_4_Update.md
│       ├── AI_Knowledge_Platform_v7_5_Update.md
│       └── Task2_Task3_Integration_Contract.md
├── config/
│   ├── defaults.yaml
│   ├── qdrant.collection.yaml
│   └── foundation/
│       ├── confluence_scope.yaml
│       ├── source_config.yaml
│       ├── sync_config.yaml
│       └── classifier_rules.yaml
├── data/
│   ├── raw/          # foundation only
│   ├── work/         # foundation only
│   ├── exports/      # boundary: indexing reads here
│   └── index/        # indexing/runtime only
├── alembic/
├── src/
│   └── knowledgenexus/
│       ├── main.py
│       ├── shared/
│       │   ├── config/
│       │   ├── logging/
│       │   ├── errors/
│       │   ├── di/
│       │   └── akp/
│       │       ├── contract_loader.py
│       │       └── schema_validator.py
│       ├── foundation/
│       │   ├── domain/
│       │   │   ├── models/
│       │   │   └── rules/
│       │   ├── ports/
│       │   ├── application/
│       │   │   ├── use_cases/
│       │   │   └── jobs/
│       │   ├── infrastructure/
│       │   │   ├── connectors/
│       │   │   ├── raw_store/
│       │   │   ├── metadata_store/
│       │   │   ├── file_store/
│       │   │   ├── processors/
│       │   │   └── exporters/
│       │   └── cli/
│       ├── indexing/
│       │   ├── domain/
│       │   │   ├── models/
│       │   │   └── rules/
│       │   ├── ports/
│       │   │   ├── chunk_read_port.py
│       │   │   ├── chunk_write_port.py
│       │   │   ├── document_read_port.py
│       │   │   ├── relation_read_port.py
│       │   │   ├── symbol_read_port.py
│       │   │   ├── vector_search_port.py
│       │   │   └── vector_write_port.py
│       │   ├── application/
│       │   │   └── use_cases/
│       │   │       └── import_akp_snapshot.py
│       │   ├── infrastructure/
│       │   │   ├── importers/
│       │   │   ├── embedding/
│       │   │   ├── repositories/
│       │   │   ├── vector_store/
│       │   │   └── database/
│       │   ├── jobs/
│       │   └── cli/
│       ├── retrieval/
│       │   ├── domain/
│       │   │   └── models/
│       │   ├── ports/
│       │   ├── application/
│       │   │   └── use_cases/
│       │   └── infrastructure/
│       │       └── query_adapters/
│       ├── chat/
│       │   ├── domain/
│       │   │   └── models/
│       │   ├── ports/
│       │   ├── application/
│       │   │   └── use_cases/
│       │   └── infrastructure/
│       │       └── llm/
│       └── presentation/
│           └── api/
│               ├── app.py
│               └── v1/
│                   ├── foundation.py
│                   ├── import_snapshot.py
│                   ├── retrieve.py
│                   ├── chat.py
│                   └── schemas/
└── tests/
    ├── architecture/
    ├── foundation/
    ├── indexing/
    ├── retrieval/
    ├── chat/
    └── integration/
```

**Implementation note (this is a target, not a scaffold).** The layout above is the canonical *destination*, not a set of empty folders to create on day one. Starting from scratch, folders/modules appear as code is written — Foundation may begin with only the Job-1 inventory path (a connector, a raw store, a CLI command) and a bounded context can be nearly empty early. What holds from the very first file is the **dependency direction (D34)** and the boundaries (D29/D30), not the presence of every folder. Absence of a folder is fine until code needs it; a *violation of the dependency rules* is not.

## D25. Bounded-context responsibilities

**Foundation** — crawl Confluence/Git/media; preserve raw data; normalize source data; build `CanonicalDocument`, `ChunkRecord`, `RelationRecord`, `ACLRecord`, `MediaAsset`, `SymbolRecord`, `SyncStateRecord`, `TombstoneRecord`; chunk by structural boundaries; validate before export; write the export snapshot. **Must not** embed, upsert Qdrant, query retrieval, or call Gauss.

**Indexing** — resolve the export snapshot; validate manifest and JSONL records; apply tombstones; embed `ChunkRecord.text` verbatim; store full chunk text + metadata in the hydrate DB; store vector + slim payload in Qdrant; own `repositories/`, `database/`, `vector_store/`.

**Retrieval** — build the search query; call vector search through Indexing read ports; hydrate via Indexing read ports; enforce ACL; rerank and relation-expand. **Must not** import `indexing.infrastructure` or `foundation`.

**Chat** — build answer context from Retrieval output; call the Gauss/LLM adapter; produce the answer and `CitationView`. **Must not** call Qdrant/SQL directly.

**Presentation** — FastAPI/API/CLI entrypoints; calls application use cases only; **no business logic**.

## D26. Foundation folder semantics

- **`foundation/domain/models/`** — internal Python models for the Foundation pipeline. Mirrors the AKP contract records, but `contracts/akp/schemas` remains authoritative.
- **`foundation/domain/rules/`** — pure deterministic, no-I/O rules: `ChunkIdGenerator`, `ContentHasher`, `TextNormalizationRules`, `AclTagPolicy`, `ScopePolicy`, `TombstonePolicy`, `JiraKeyPolicy`. No network, no filesystem, no DB.
- **`foundation/ports/`** — interfaces required by application use cases: `SourceConnectorPort`, `RawStorePort`, `MetadataStorePort`, `FileStorePort`, `ExporterPort`, `ClockPort`.
- **`foundation/application/use_cases/`** — one business action each: `BuildConfluenceInventory`, `CrawlConfluenceScope`, `ScanGitRepository`, `NormalizeDocuments`, `BuildChunks`, `ExtractRelations`, `ExtractACL`, `ProcessMediaAssets`, `BuildSymbolIndex`, `ExportDataset`.
- **`foundation/application/jobs/`** — pipeline composition over use cases: `ConfluenceInventoryJob`, `ConfluenceFullSyncJob`, `GitScanJob`, `BuildDatasetJob`, `ExportDatasetJob`.
- **`foundation/infrastructure/connectors/`** — concrete adapters for Confluence/Git/Gerrit/Jira-stub; handles API, auth, pagination, rate limit, retry. Must not chunk/export/embed.
- **`foundation/infrastructure/raw_store/`** — saves raw API/source responses for audit and reprocessing.
- **`foundation/infrastructure/metadata_store/`** — Foundation-internal checkpoint/sync/content-hash/tombstone state. **Not** the Indexing hydrate DB.
- **`foundation/infrastructure/file_store/`** — stores downloaded attachments/media files.
- **`foundation/infrastructure/processors/`** — concrete parser/extractor implementations using libraries: `scope_filter`, `html_to_markdown`, `normalizer`, `chunker`, `relation_extractor`, `acl_extractor`, `media`, `symbol_indexer`. Pure rules stay in `domain/rules`; orchestration stays in `application/use_cases`.
- **`foundation/infrastructure/exporters/`** — writes JSONL, manifest, quality_report, LATEST.txt; must validate records before writing; **no `qdrant_payload_exporter`**.
- **`foundation/cli/`** — operator/dev commands that call application jobs; no business logic.

## D27. Runtime configuration boundary

```
AKP_CONTRACT_ROOT=./contracts/akp
AKP_EXPORT_ROOT=./data/exports
AKP_DATASET_NAME=spen_knowledge_poc
AKP_USE_LATEST=true
AKP_DATASET_VERSION=<optional explicit version>
```

Importer resolution:

1. If `AKP_USE_LATEST=true`, read `${AKP_EXPORT_ROOT}/${AKP_DATASET_NAME}/LATEST.txt`; otherwise use `AKP_DATASET_VERSION`.
2. Resolve `${AKP_EXPORT_ROOT}/${AKP_DATASET_NAME}/${dataset_version}`.
3. Validate `manifest.dataset_version == dataset_version`.
4. Validate every JSONL record against `${AKP_CONTRACT_ROOT}/schemas`.
5. Import into the hydrate DB + Qdrant per the v7.4 contract (tombstones, deterministic point IDs, ACL payload, verbatim embedding).

Paths are repo-relative in a single-repo deployment. `AKP_EXPORT_ROOT` points at `data/exports` only — `data/raw` and `data/work` are never referenced.

## D28. Secret and PAT configuration

- PAT/token/password **must never be committed**.
- YAML config may reference **secret names only**, never secret values.
- `.env.local` is allowed for POC and **must be gitignored**; `.env.example` contains empty placeholders only.
- `source_config.yaml` uses `token_env`, e.g.:

```yaml
auth:
  type: bearer_pat
  token_env: CONFLUENCE_PAT
```

- `shared/config/settings.py` loads YAML + env; `shared/config/secret_provider.py` resolves `token_env` (or a future `secret_ref`).
- Connectors receive **resolved credentials via DI/config objects**, not by reading env directly.
- Logs, quality reports, errors, and exported records **must never print token values**.
- POC may use a personal PAT; production should use a service account / secret manager.

## D29. Storage ownership and read ports

- **Indexing owns physical storage implementations:** `indexing/infrastructure/repositories/`, `indexing/infrastructure/database/`, `indexing/infrastructure/vector_store/`.
- **Retrieval must not import `indexing.infrastructure.*`** — it reads through Indexing **read ports** only.
- Indexing ports: `ChunkReadPort`, `ChunkWritePort`, `DocumentReadPort`, `RelationReadPort`, `SymbolReadPort`, `VectorSearchPort`, `VectorWritePort`.
- `indexing.infrastructure` implements these ports; `retrieval.infrastructure.query_adapters` may delegate to them, wired by DI.
- **Rule:** Retrieval depends on `indexing.ports`, never `indexing.infrastructure`.

## D30. Domain model ownership

- **`indexing/domain`** owns the persistence/write model: `Document`, `Chunk`, `IngestJob`, `Relation`, `ACL`, `Symbol`, `MediaAsset`.
- **`retrieval/domain`** owns the read model: `SearchQuery`, `RetrievedChunk`, `SearchResult`, `RankingSignal`.
- **`chat/domain`** owns the answer/presentation model: `ChatMessage`, `Answer`, `CitationView`.
- AKP `ChunkRecord` maps to `indexing.domain.Chunk` inside `import_akp_snapshot`.
- Retrieval does not reuse an Indexing entity directly in use cases; adapters map Indexing read output → `RetrievedChunk`.
- **`shared/` must not contain business entities.**

## D31. Shared AKP validator

- Avoid duplicate JSON-Schema validation implementations.
- Add `shared/akp/schema_validator.py` and `shared/akp/contract_loader.py`.
- **Foundation uses the shared validator before writing** the export; **Indexing uses the same shared validator before importing** the snapshot.
- Business validation stays in each application use case: tombstone `entity_type` behavior, delta ordering, `config_hash` invalidation, ACL deny-safe checks.

## D32. Chunking / input-text coverage rule

Foundation does not create arbitrary short snippets. For every in-scope document, Foundation converts all semantically meaningful normalized content into `ChunkRecord`s (or explicit side records / placeholders).

- Wiki content is chunked by heading sections, paragraph windows, table row groups, and fenced code blocks.
- Code is chunked by tree-sitter symbols, oversize-symbol windows, or fallback line windows.
- Media extracted text is attached to parent document/media provenance.
- Text must not be silently dropped.
- Chunking may normalize whitespace, remove non-semantic markup, split oversize units, and add controlled overlap.
- Every omission must be scope-driven, policy-driven, or reported in `quality_report.md`.
- Every `ChunkRecord.text` includes the breadcrumb/path/symbol prefix where applicable.
- Every `ChunkRecord.text` is normalized **before** `token_count`, `content_hash`, and `chunk_id`.
- Indexing embeds `ChunkRecord.text` **verbatim**.

## D33. Vector DB vs hydrate DB text rule

- The **hydrate DB (PostgreSQL/SQLite)** stores full `ChunkRecord.text` and full chunk metadata.
- **Qdrant** stores the vector generated from `ChunkRecord.text` and a **slim payload only** — at least `chunk_id`, `document_id`, `dataset_name`, `dataset_version`, `source_system`, `source_type`, `content_kind`, plus ACL/filter/provenance fields.
- Qdrant should **not** store full `ChunkRecord.text`. An optional preview/title/snippet is allowed **only for debugging**, never as source of truth.
- **LLM context is hydrated from the hydrate DB via `chunk_id`**, not from the Qdrant payload.
- The text used for embedding must equal the text stored as `ChunkRecord.text`.

## D34. Bounded-context dependency rules

**Allowed:**
- `presentation` → application use cases
- `chat.application` → `retrieval.ports` or `retrieval.application`
- `retrieval.application` → `indexing.ports` (read side)
- `indexing.application` → `contracts/akp` + `data/exports` (not Foundation Python modules)
- `foundation` → `contracts/akp` + `shared` only

**Forbidden:**
- `indexing` → `foundation`
- `foundation` → `indexing` / `retrieval` / `chat`
- `retrieval` / `chat` → `indexing.infrastructure`
- `chat` → `vector_store` / `database` directly
- any module except `foundation` → `data/raw` or `data/work`
- `shared` → business domain logic

Enforce with **import-linter** (or equivalent) architecture tests in CI (`tests/architecture/`).

## D35. Operational pieces

The canonical tree must include:

- `src/knowledgenexus/main.py` or `presentation/api/app.py` as the app entry point.
- `alembic/` at repo root.
- DB models under `indexing/infrastructure/database/`.
- `indexing/cli/` for import/index jobs (e.g. `kn-indexer import`).
- `foundation/cli/` for crawl/export jobs (e.g. `kn-foundation crawl` / `export`).
- `shared/akp/` for the schema validator and contract loader.
- `tests/architecture/` for dependency rules.
- `contracts/akp` includes `Task2_Task3_Integration_Contract.md` and `embedding_profile.yaml`.
- `.env.example` exists; `.env.local` is gitignored.

---

# Part B — Why not v8 yet

- v7.5 is a **non-breaking layout / dependency clarification** — no schema, ownership, or consumer-contract-semantic change.
- **v8 is reserved** for a consolidated master spec after the POC, or for genuinely breaking changes: a schema **major** bump, an ownership redesign, replacing the export contract, or a **major runtime-architecture replacement**.
- Until then, keep **layered decision logs** (v7.x) on top of Master v7.1.

---

# Part C — Acceptance criteria

1. Part 1 / Foundation can run and export **without Indexing initialized** (and without KnowledgeNexus runtime installed).
2. Indexing can import a snapshot **without importing any Foundation module**.
3. Retrieval can run using **Indexing read ports only**.
4. Changing Foundation's `data/raw/` or `data/work/` layout **does not affect** Indexing/Retrieval/Chat.
5. Changing the export schema requires **schema/version handling** (validation + `schema_version`/`schemas_version` checks), not code-folder coupling.
6. **CI fails if `indexing` imports `foundation`.**
7. **CI fails if `retrieval` or `chat` imports `indexing.infrastructure`.**
8. **CI fails if any non-Foundation module reads `data/raw` or `data/work`.**
9. CI validates a sample export using `shared/akp/schema_validator.py` (a golden `sample_export/` fixture).
10. Qdrant payload does **not** contain full `ChunkRecord.text` (except an optional debug preview).
11. PAT/token values do **not** appear in committed config, logs, `quality_report.md`, or exports.

---

# Open questions (layout)

- **Sample export fixture owner** — who maintains the golden `sample_export/` used by CI acceptance criteria 9, and where under the repo it lives (validated by both Foundation-export and Indexing-import tests).
- **import-linter ruleset** — encode D34 as concrete import-linter contracts in `tests/architecture/`; agree the exact layer names/paths.
- **Contracts single-source** — `contracts/akp/` is now one in-repo location shared by Foundation (validate-before-export) and Indexing (validate-before-import); confirm no second copy is introduced. The earlier cross-repo "vendored copy / sync mechanism / transport" questions are dissolved by the single-repo model.
- **DI container** — `shared/di/` wiring for cross-context ports (Retrieval → Indexing read ports; Chat → Retrieval) — choose the DI approach.
