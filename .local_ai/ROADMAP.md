# Foundation Implementation Roadmap

This file is local execution guidance, not a normative contract.

Last workspace verification: 2026-07-10.

Precedence:
1. `contracts/foundation/schemas/`
2. `contracts/foundation/CHUNKING_SPEC.md`
3. Normative Foundation architecture and integration contracts
4. `.local_ai/PROJECT_CONTEXT.md`
5. `.local_ai/IMPLEMENTATION_STATE.md`
6. This roadmap

If this roadmap conflicts with an actual schema or normative contract, the schema
or normative contract wins.

JSON Schemas are the source of truth for export record shapes. Foundation owns
crawl, raw preservation, normalization, chunking, ACL, relations, media, symbols,
sync state, tombstones, and export snapshots. Foundation does not own embedding,
Qdrant, hydrate DB indexing, retrieval, reranking, chat, Gauss, or user-facing
RAG. Foundation record builders create plain JSON-compatible dictionaries, and
JSON Schema validation remains the final authority. This roadmap must not be used
as permission to implement future milestones early.

## Project Identity

- Product: KnowledgeNexus.
- Current bounded context: Foundation.
- AKP is a historical name and should not be introduced into new Python
  namespaces unless an existing contract filename still uses it.
- Contract root: `contracts/foundation/`.
- Schema root: `contracts/foundation/schemas/`.
- Shared schema loader/validator:
  `src/knowledgenexus/shared/contracts/foundation/`.
- Foundation source root: `src/knowledgenexus/foundation/`.

Preferred architecture is a single product repository with bounded contexts.
Absence of future folders is not a problem. The canonical tree is a destination
guide, not an instruction to scaffold empty folders.

Sync-state clarification:
- Foundation owns sync/checkpoint semantics.
- The authoritative mutable sync state lives in Foundation's SQLite metadata
  store or equivalent `MetadataStorePort` implementation.
- `sync_state.jsonl` is only an exported snapshot/diagnostic representation of
  that state.
- M2C, M3, and M4 must not be interpreted as requiring the crawler checkpoint
  database or resumability implementation early.
- A `SyncStateRecordBuilder` may be deferred until the crawler/checkpoint flow
  exists, unless a contract fixture explicitly needs a representative exported
  `SyncStateRecord`.

## 1. Current Status

| Milestone | Status | Evidence | Notes |
|---|---|---|---|
| M0A - Minimal scaffold | done | Package roots, `.env.example`, `.gitignore`, contract root present | Some repo files are untracked locally; status is based on workspace evidence. |
| M1 - Shared Foundation schema loader/validator | done | `contract_loader.py`, `schema_validator.py`, tests under `tests/shared/contracts/foundation/` | Dict and JSONL validation exist. |
| M2A - Pure text/hash/chunk-ID rules | done | `ContentHasher`, `TextNormalizationRules`, `ChunkIdGenerator`, pipeline tests | Chunk ID generation stays separate from current builders unless a focused task says otherwise. |
| M2B - Deterministic entity ID helpers | done | Relation, ACL, Tombstone, Document ID helpers plus `hashing_constants.py` and tests | `DocumentIdGenerator.source_entity_id()` remains a generic helper, not a strategy layer. |
| M2C - Schema-shaped record builders | done | CanonicalDocument, Chunk, Relation, and ACL builders implemented and tested; M2C5 gate closed | Remaining builders are deferred until activated by later milestones. |
| M2D - Contract sample set and cross-record invariants | done | Coherent Document + Chunk + Relation + ACL sample graph implemented and tested | Fixture-backed graph is reusable by M3 exporter tests. |
| M3 - Full-snapshot export foundation | done | M3A through M3F implemented and tested | Completed staging is published by same-parent rename and advertised through atomic `LATEST.txt` replacement. |
| M4 - Golden sample export | done | Committed deterministic fixture plus end-to-end M3 generation/validation tests | Uses synthetic data only and exact byte comparison. |
| M5A - Confluence inventory core and scope policy | done | Typed config/metadata/items, port, use case, deterministic reports, unit/integration tests | Deployment-independent; contains no HTTP. |
| M5B-1 - Data Center response parsing and normalization | done | Pure mapper, numeric envelope parser, sanitized fixtures, and focused tests | Root remains compatible with the captured payload; no HTTP behavior. |
| M5B-2 - Data Center HTTP adapter and pagination | done | Independent review approved; offline fake-HTTP tests and full Foundation/Shared suite pass | Owns strict root-space verification, root-scoped CQL, numeric pagination, and a bounded HTTPS JSON transport. |
| M5C-1 - Reviewed safe smoke runner | implemented; review pending | `foundation/cli/` entrypoint composing approved components, runbook, and 40 offline tests | Adds no HTTP/CQL/pagination/parsing of its own; zero cross-context imports per D34; no live run on this machine. |
| M5C-2 - Live inventory run on main machine | planned | Depends on M5C-1 review and Confluence access | One small real inventory on the M5B-0 test root; first live confirmation of `expand=space,version`. |
| M6-0 - Confluence page fetch live evidence | done | Operator live probe on the primary machine; approved sanitized conclusion registered in state and `.local_ai/review/m6-0-...` | Confirms page/restriction/attachment request shapes; no raw artifact in repo by design. |
| M6A - Fetch and preserve one raw page | implemented; pending detached review + live run | Review stack `0948252..a8623d4`; 700 Foundation/Shared tests pass; `.local_ai/review/m6a-raw-page-fetch-summary.md` | Adds raw-byte transport capability + atomic raw page store; no normalization/ACL/attachment. |
| M6 (B-G) - Rest of one-page vertical slice | planned | Depends on M6A raw provenance | Restrictions/ACL, normalization, chunking, relation, export end to end. |
| M7 - Crawl reliability and scale | planned | No crawler reliability layer yet | Retry, rate limit, checkpoint, resume. |
| M8 - Production-quality normalization and chunking | planned | Only early text normalization and chunk ID rules exist | Structure-aware processing later. |
| M9 - Media, Git, symbols, and deletion propagation | planned | Media/symbol/tombstone record schemas exist; no processing tracks yet | Split into independent tracks. |
| M10 - First full POC Foundation snapshot | planned | Requires export, the real Confluence path, and the required POC media/Git/symbol tracks | Real delta/deletion propagation is required before the second sync or first delta export, not before the initial `full_snapshot`. |

## 2. Current Task

Current area: M5C small real inventory smoke run.

- M2C1 `CanonicalDocumentRecordBuilder` - done.
- M2C2 `ChunkRecordBuilder` - done; source/test files and review artifacts
  reflect the approved cleanup.
- M2C3 `RelationRecordBuilder` - done.
- M2C4 `ACLRecordBuilder` - done.
- M2C5 builder review gate - done.
- M2D coherent contract sample set - done.

Evidence used:
- `src/knowledgenexus/foundation/domain/records/canonical_document_record_builder.py`
- `src/knowledgenexus/foundation/domain/records/chunk_record_builder.py`
- `src/knowledgenexus/foundation/domain/records/relation_record_builder.py`
- `src/knowledgenexus/foundation/domain/records/acl_record_builder.py`
- `tests/foundation/domain/records/test_canonical_document_record_builder.py`
- `tests/foundation/domain/records/test_chunk_record_builder.py`
- `tests/foundation/domain/records/test_relation_record_builder.py`
- `tests/foundation/domain/records/test_acl_record_builder.py`
- `.local_ai/review/m2c2-chunk-record-builder-review-summary.md`
- `.local_ai/review/m2c2-chunk-record-builder.patch`
- `.local_ai/review/m2c3-relation-record-builder-review-summary.md`
- `.local_ai/review/m2c4-acl-record-builder-review-summary.md`
- `.local_ai/review/m2c5-builder-gate-review-summary.md`

Current objective:
- Run M5C with authentication resolved outside the non-secret M5A source
  config.
- Confirm the previously unobserved root `expand=space,version` shape on the
  connected machine.
- Begin with a conservative search `page_size` and observe the deployment's
  actual cap; server-clamped limits already fail closed in M5B-2.

Likely files for M3A:
- `src/knowledgenexus/foundation/infrastructure/exporters/jsonl_record_writer.py`
- `tests/foundation/infrastructure/exporters/test_jsonl_record_writer.py`

Placement note:
`JsonlRecordWriter` is a concrete filesystem serialization adapter, so it lives
under `foundation/infrastructure/exporters` rather than the application layer.

M3A completion evidence:
- `src/knowledgenexus/foundation/infrastructure/exporters/jsonl_record_writer.py`
- `tests/foundation/infrastructure/exporters/test_jsonl_record_writer.py`
- `.local_ai/review/m3a-jsonl-record-writer-review-summary.md`
- `.local_ai/review/m3a-jsonl-record-writer.patch`

M3B completion evidence:
- `src/knowledgenexus/foundation/domain/rules/dataset_version_generator.py`
- `tests/foundation/domain/rules/test_dataset_version_generator.py`
- `.local_ai/review/m3b-dataset-version-generator-review-summary.md`
- `.local_ai/review/m3b-dataset-version-generator.patch`

Finalized M3B dataset_version convention:
- `vYYYYMMDD-HHMMSS-ffffffZ`
- input instant must be timezone-aware;
- input is converted to UTC before formatting;
- the generator does not acquire the current time.

Producer-policy note:
- `dataset_version` affects the producer snapshot folder name, but downstream
  consumers must continue treating it as an opaque string.
- The only cross-boundary contract dependency is equality between folder name,
  `manifest.dataset_version`, and `LATEST.txt` content.
- When a committed Foundation export-conventions decision log exists, record
  this producer convention there so it does not live only in code and local
  steering files.

M3C completion evidence:
- `src/knowledgenexus/foundation/domain/records/manifest_record_builder.py`
- `tests/foundation/domain/records/test_manifest_record_builder.py`
- `.local_ai/review/m3c-manifest-record-builder-review-summary.md`
- `.local_ai/review/m3c-manifest-record-builder.patch`

M3C.1 completion evidence:
- `src/knowledgenexus/shared/contracts/foundation/schema_validator.py`
- `tests/shared/contracts/foundation/test_schema_validator.py`
- `.local_ai/review/m3c1-foundation-format-checker-review-summary.md`
- `.local_ai/review/m3c1-foundation-format-checker.patch`

M3C.1 operational follow-up: done in the public `README.md`.
- Setup uses `python -m pip install -r requirements.txt`.
- The README explains `rfc3339-validator`, `jsonschema.FormatChecker`, and the
  current unpinned-dependency policy.

M3D completion evidence:
- `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_writer.py`
- `tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py`
- `.local_ai/review/m3d-full-snapshot-staging-writer-review-summary.md`
- `.local_ai/review/m3d-full-snapshot-staging-writer.patch`

M3D staging snapshot decisions:
- M3D constructs only the machine-readable staging snapshot.
- It writes eight JSONL files plus `manifest.json`.
- It intentionally does not write `quality_report.md`, `LATEST.txt`, or a final
  dataset-version directory.
- Count keys match JSONL basenames: `documents`, `chunks`, `relations`, `acl`,
  `media_assets`, `symbols`, `sync_state`, and `tombstones`.
- Exact staging verification checks every direct child entry, not only regular
  files filtered by name; unexpected directories and symlinks are rejected.
- Generic `Mapping` records are copied to a plain `dict` one record at a time
  before validation and writing, matching the M3A public API decision without
  materializing full streams.
- M3 sequencing correction: `quality_report.md` is required for a complete POC
  export, so finalization and `LATEST.txt` update must happen only after
  staging is contract-complete.

M3E completion evidence:
- `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_completer.py`
- `tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py`
- `.local_ai/review/m3e-full-snapshot-staging-completer-review-summary.md`
- `.local_ai/review/m3e-full-snapshot-staging-completer.patch`

M3E staging completion decisions:
- M3E requires exactly the nine M3D machine-readable files before it starts.
- It loads and schema-validates `manifest.json`, then enforces the approved
  full-snapshot producer invariants without recounting JSONL files.
- It writes deterministic `quality_report.md` and requires exactly ten regular,
  non-symlink files after completion.
- M3E owns only its temporary report and newly created `quality_report.md`; it
  never removes staging or machine-readable files on failure.
- The minimal report describes construction metadata and checks actually
  performed. Master Spec v7.1's final POC skips, failures, and coverage warnings
  remain deferred until real pipeline evidence exists.
- M3E does not publish, move staging, or create `LATEST.txt`.

M3C schema findings:
- Required Manifest fields are `schema_version`, `dataset_version`,
  `export_mode`, `generated_at`, `config_hash`, `chunker_version`,
  `schemas_version`, and `counts`.
- Optional Manifest fields are `base_dataset_version` and `source_scopes`.
- `base_dataset_version` delta semantics are not encoded in JSON Schema and
  remain a later orchestration responsibility.
- `counts` has arbitrary string keys and non-negative integer values.
- `source_scopes` is an optional free-form object.
- M3C.1 follow-up: the shared Foundation validator now enforces JSON Schema
  `format: date-time` for both direct record validation and JSONL validation.

Explicitly out of scope:
- No manifest generation.
- No real filesystem snapshot.
- No connector or real Confluence content.
- No embedding, indexing, retrieval, or chat.

## 3. M2C - Schema-Shaped Record Builders

Purpose:
Create small, schema-driven builders that return plain JSON-compatible dicts.
These builders are not complete typed domain models and do not perform JSON
Schema validation internally.

Global M2C rules:
- Read the actual schema before implementation.
- Read `defs.schema.json` for referenced enums, IDs, hashes, ACL tags, and
  timestamps.
- The schema wins over examples and suggested APIs.
- Return `dict[str, object]`.
- Do not use Pydantic or ORM.
- Do not add unknown top-level fields.
- Do not validate the full JSON Schema inside builders.
- Tests must validate built records with `FoundationSchemaValidator`.
- Keep schema-facing enum-like values as strings unless a typed-model milestone
  explicitly introduces enums.
- Keep timestamps as schema-facing strings.
- Copy mutable list/dict inputs when records retain them.
- Do not implement connector, chunker, exporter, Qdrant, SQLite, retrieval, or
  chat behavior inside a builder task.
- Each task should implement one record concept only.

### M2C1 - CanonicalDocumentRecordBuilder

Status: done.

Purpose:
- Create schema-valid `CanonicalDocument` records.
- Compute `content_hash` from `normalized_body_text`.
- Do not expose `normalized_body_text` unless the schema has that field.
- Do not add historical fields such as `body_text`, `raw_uri`, `parent_ids`, or
  `labels` if the current schema does not contain them.

### M2C2 - ChunkRecordBuilder

Status: done.

Purpose:
- Accept `chunk_id` from the caller.
- Accept `token_count` from the caller.
- Accept `chunker_version` from the caller.
- Treat `text` as already normalized.
- Compute `content_hash` from `text`.
- Do not generate `chunk_id`.
- Do not split or tokenize text.
- Validate records in tests with `FoundationSchemaValidator`.

### M2C3 - RelationRecordBuilder

Status: done.

Purpose:
- Build `RelationRecord` according to
  `contracts/foundation/schemas/relation_record.schema.json`.
- Return a plain JSON-compatible dict.
- Do not extract or resolve relations.

Schema clarification:
- Inspect the schema's required array directly.
- In the current schema, required fields are `schema_version`, `relation_id`,
  `source_id`, `target_id`, `relation_type`, `resolution_status`, and
  `created_at`.
- `evidence` and `confidence` are optional schema fields.
- Do not make `evidence` or `confidence` required merely because this roadmap
  says the builder may accept them.
- Follow the schema for whether optional fields should be omitted or emitted
  with null/default values.
- Do not duplicate enum, range, pattern, timestamp, or cross-field schema
  validation inside the builder.

ID ownership:
- Use `RelationIdGenerator` only if the focused M2C3 task explicitly decides
  that `RelationRecordBuilder` owns `relation_id` generation.
- Otherwise accept `relation_id` from the caller.
- Do not silently change this responsibility inside the implementation.

Out of scope:
- No Jira-key extraction.
- No page-link discovery.
- No target hydration.
- No external API calls.
- No relation graph expansion.

Required completion evidence:
- Focused unit tests.
- At least one Jira relation sample.
- At least one non-Jira relation sample if supported by the actual schema.
- All built records pass `FoundationSchemaValidator`.
- Deterministic `relation_id` behavior is tested only if generation belongs to
  this builder.

### M2C4 - ACLRecordBuilder

Status: done.

Purpose:
- Build `ACLRecord` according to `acl_record.schema.json`.
- Preserve deny-safe ACL semantics.
- Represent unresolved access as `restricted:unresolved` where the contract
  requires.
- Copy all principal/tag lists.
- Accept effective ACL output from caller.
- Do not fetch Confluence restrictions.
- Do not expand group membership.
- Do not implement query-time authorization.

Required completion evidence:
- Unrestricted sample.
- Restricted sample.
- Unresolved/default-deny sample.
- Schema validation passes.
- `acl_tags` is never empty where schema forbids it.

### M2C5 - Just-in-time builder review gate

Status: done.

Result:
- Do not activate any additional record builder now.
- Close M2C.
- Proceed to M2D.

Do not automatically implement all remaining builders.

Before implementing each deferred builder, inspect upcoming consumers and decide
whether the builder is needed immediately:

- `MediaAssetRecordBuilder`: implement before M4 only if the golden sample
  export needs a non-empty media record or the exporter requires a builder-backed
  media sample; otherwise defer until media ingestion.
- `SyncStateRecordBuilder`: prefer implementation near crawler/checkpoint work
  because sync-state semantics depend on actual jobs; implement earlier only if
  manifest/sample-export acceptance requires a real sync-state sample.
- `TombstoneRecordBuilder`: a full-snapshot POC may contain an empty
  `tombstones.jsonl`; defer real tombstone production until deletion/update
  propagation unless fixtures require representative tombstone records.
- `SymbolRecordBuilder`: defer until symbol indexer work, together with
  `SymbolIdGenerator` and parser/indexer semantics.

For every deferred builder, record the defer reason, activation milestone, and
dependency that must exist first.

## 4. M2D - Contract Sample Set and Cross-Record Invariants

Entry condition:
- M2D starts only after, at minimum, M2C3 `RelationRecordBuilder` and M2C4
  `ACLRecordBuilder` are complete.
- `CanonicalDocumentRecordBuilder` and `ChunkRecordBuilder` alone are not enough
  because the coherent sample graph requires valid `RelationRecord` and
  `ACLRecord` instances.
- MediaAsset, SyncState, Tombstone, and Symbol records are not mandatory for the
  first M2D graph unless an active contract test requires them.

M2D is not only more schema validation tests. Builder tests already validate
individual records. M2D creates a coherent, tiny in-memory record graph.

Recommended location:
- `tests/fixtures/foundation/record_factories.py`
- `tests/fixtures/foundation/sample_record_set.py`

Do not create static exported JSONL snapshots yet unless the exporter exists.

Objectives:
- Create a deterministic `CanonicalDocument` sample.
- Create at least one `ChunkRecord` linked to it.
- Create an `ACLRecord` linked to the same document.
- Create a `RelationRecord` linked consistently.
- Include media/sync/tombstone samples only when needed.
- Validate all records with `FoundationSchemaValidator`.
- Test cross-record references.

Required cross-record invariants:
- Every `ChunkRecord.document_id` references an existing document.
- Every `ACLRecord.document_id` references an existing document.
- `relation_ids` on chunks reference existing `RelationRecord`s.
- ACL tags on a chunk are compatible with the sample ACL record.
- Record IDs are unique within their record type.
- The sample set is deterministic.
- No record contains unknown fields.
- Mutable fixture inputs are not shared accidentally.

Out of scope:
- No JSONL writing.
- No manifest generation.
- No real filesystem snapshot.
- No connector.
- No real Confluence content.
- No embedding or indexing.

Completion gate:
- All individual records validate.
- All cross-record tests pass.
- Record factories are reusable by M3 exporter tests.
- Sample data is small and human-readable.

## 5. M3 - Full-Snapshot Export Foundation

Purpose:
Implement a safe, deterministic full-snapshot writer using only manual or
fixture-backed records. No real source ingestion yet.

### M3A - JsonlRecordWriter

Responsibilities:
- Serialize caller-provided JSON-compatible records as one JSON object per line.
- Use deterministic UTF-8 output and deterministic newline behavior.
- Preserve caller-provided record order.
- Do not load schemas and do not perform Foundation contract validation.
- Do not know about Confluence, Git, manifests, or snapshot layout.

Tests:
- One record.
- Multiple records.
- Unicode.
- Deterministic bytes.

### M3B - DatasetVersionGenerator and controlled clock boundary

Responsibilities:
- First inspect whether the active Foundation contract or decision log defines
  a `dataset_version` naming convention.
- If no normative convention exists, raise and record that decision before
  implementing the generator; do not invent a format silently.
- After the convention is approved, generate a Windows-safe `dataset_version`.
- Use an injected/controlled clock so tests are deterministic.
- Ensure the generated value satisfies `manifest.schema.json`.
- Do not introduce datetime objects into schema-facing builders unless the
  project explicitly adds a formatting helper.

Move `DatasetVersionGenerator` from backlog to active work here.

### M3C - ManifestRecordBuilder

Responsibilities:
- Follow `manifest.schema.json` exactly.
- Accept dataset/version/export metadata and all actual schema fields.
- No filesystem scanning inside the builder.
- No schema validation inside the builder.
- Counts are caller-provided or produced by the snapshot orchestrator.

### M3D - FullSnapshotStagingWriter

Status: done.

Responsibilities:
- Accept explicit `staging_path`; it must not already exist and its parent must
  already exist.
- Create and own the staging directory.
- Validate records before yielding them to `JsonlRecordWriter`.
- Materialize each generic `Mapping` record to a plain `dict` one record at a
  time before validation and writing.
- Write these exact JSONL files, including zero-byte files for empty streams:
  `documents.jsonl`, `chunks.jsonl`, `relations.jsonl`, `acl.jsonl`,
  `media_assets.jsonl`, `symbols.jsonl`, `sync_state.jsonl`, and
  `tombstones.jsonl`.
- Use actual counts returned by `JsonlRecordWriter`.
- Build and validate a `full_snapshot` Manifest, then write deterministic
  `manifest.json`.
- Verify the successful staging directory contains exactly the nine
  machine-readable regular files, with no unexpected child directories or
  symlinks.
- Remove the owned staging directory on post-creation failure.

Out of scope:
- No final publish.
- No `LATEST.txt`.
- No `quality_report.md`.
- No delta export.
- No locking, recovery journals, checksums, or retry loops.

### M3E - Minimal quality report / contract-complete staging

Responsibilities:
- Generate a deterministic human-readable `quality_report.md` in staging.
- Include record/file counts.
- Include validation/export warnings.
- No secret values.
- No PAT/token values.
- Verify staging is contract-complete before finalize is allowed.
- Do not publish the final snapshot directory.
- Do not update `LATEST.txt`.

### M3F - Atomic finalize + LATEST.txt

Rules:
- Move/rename a validated staging directory to the final
  `data/exports/<dataset_name>/<dataset_version>/` directory.
- The final dataset directory must never become visible as complete before all
  required machine-readable files, `quality_report.md`, and manifest validation
  succeed.
- `LATEST.txt` is updated only after the final snapshot is complete.
- A failed finalize must leave the previous `LATEST.txt` value intact.
- Avoid symlink-based behavior.

Validate before or during finalize:
- Folder `dataset_version` equals `manifest.dataset_version`.
- Required machine-readable files exist.
- Manifest counts equal JSONL line counts.
- Every JSONL record validates.
- `schemas_version` is recognized.
- `export_mode` is valid.
- No exported artifact may require Indexing or another consumer to read
  Foundation `data/raw` or `data/work`.

M3 out of scope:
- No Confluence API.
- No raw crawl.
- No normalization.
- No real chunking.
- No embedding.
- No Qdrant.
- No SQLite/PostgreSQL.
- No delta import.
- No real deletion detection.

M3 completion gate:
- Fixture-backed full snapshot is written safely.
- Failure cannot update `LATEST.txt`.
- Final snapshot validates.
- Manifest counts are correct.
- Output bytes are deterministic for deterministic inputs.

## 6. M4 - Golden Sample Export

Status: done.

Purpose:
Create a tiny deterministic full snapshot generated by the real M3 exporter from
manual or fixture-backed records.

Expected export layout, subject to the actual Foundation export and integration
contracts in the repository:

```text
data/exports/<dataset_name>/
  LATEST.txt
  <dataset_version>/
    manifest.json
    documents.jsonl
    chunks.jsonl
    relations.jsonl
    acl.jsonl
    media_assets.jsonl
    symbols.jsonl
    sync_state.jsonl
    tombstones.jsonl
    quality_report.md
```

Important:
- This filename list is an expected handoff layout, not a rule inferred solely
  from `manifest.schema.json`.
- Before implementing M3/M4, inspect the current Foundation export contract and
  integration contract.
- If the current contract differs from this roadmap, follow the contract and
  update the roadmap.
- Do not invent additional files merely because they appeared in an older spec
  example.
- Empty JSONL files may be used only where the active export contract permits
  them.
- Writing `sync_state.jsonl` does not make the export directory the mutable
  checkpoint store. Export snapshots are immutable handoff artifacts.

Committed test fixture:
- `tests/fixtures/foundation/golden_full_snapshot/`

This golden fixture supports Foundation export validation tests and should later
support Indexing snapshot importer tests and CI contract compatibility tests.

Implemented shape:
- Fixed dataset version `v20260714-000000-000000Z`.
- Synthetic graph with 1 document, 2 chunks, 1 relation, 1 ACL, 1 media asset,
  0 symbols, 1 sync-state record, and 0 tombstones.
- Wiki chunk text includes the active breadcrumb and preserves the fenced `cpp`
  code block; Git/Symbol fixture semantics remain deferred to M9.
- Media identity uses the existing deterministic Confluence attachment ID
  convention.
- Generated through M3D -> M3E -> M3F with one-pass record streams.
- Compared by exact relative paths and bytes against the committed fixture.
- No production APIs, connectors, dependencies, or real-source data added.

M4 gates:
- `LATEST.txt` resolves to the sample version.
- Folder name equals `manifest.dataset_version`.
- Manifest counts match files.
- All records validate.
- Cross-record references remain valid after serialization.
- Sample export can be regenerated deterministically.
- No PAT/token values appear.
- No full-text/vector/indexing behavior is introduced.

M4 result:
- All gates satisfied; proceed to M5 Confluence inventory.
- Real source metadata begins in M5; the first real document body remains M6.

## 7. M5 - Confluence Inventory

Purpose:
Establish deterministic scope before expensive page/media crawling without
guessing the Confluence deployment or API.

### M5A - Confluence inventory core and scope policy

Status: done.

- Non-secret source-scope config, normalized page metadata, and deterministic
  inventory items.
- Deployment-independent inventory port with no raw API/pagination envelope.
- Root presence/scope validation, overlapping-root deduplication, duplicate
  conflict detection, and structural ordering.
- Pure include/exclude policy. Keywords remain hints and excluded pages remain
  visible for audit.
- Deterministic `pages_inventory.jsonl` and `inventory_report.csv` work
  artifacts.
- Contains no HTTP, authentication, environment resolution, connector, or
  pagination implementation.

### M5B-1 - Data Center response parsing and normalization

Status: done.

- Confirmed Confluence Data Center, Bearer PAT, `/rest/api/content/{id}` root
  fetch, and `/rest/api/search` descendant enumeration.
- The sanitized packet establishes nested content shape and a real four-window
  request sequence. Its `totalSize`/`searchDuration` values are deliberate
  negative sanitizer sentinels; committed fixtures therefore use synthetic,
  internally consistent pagination values matching the recorded terminal rule.
- Pure response mapping validates and normalizes the separately fetched root,
  root-relative descendant ancestors, parent derivation, versions, labels, and
  numeric envelope terminal state.
- Root mapping accepts the captured missing-space shape by using the expected
  space, but validates any observed `space.key`; absent root labels normalize to
  `()`.
- CQL search is index-backed, so recently changed pages may appear after a short
  delay. M5B-1 intentionally adds no sleeps or retries.
- Contains no HTTP, authentication, environment loading, CQL construction, or
  pagination loop.

### M5B-2 - Data Center HTTP adapter and pagination

Status: done; independently approved.

- Inject resolved connection/authentication configuration; never place PAT in
  M5A config, logs, exceptions, or reports.
- Fetch the root with `expand=space,version`; require root `space.key` to be
  present and equal to the configured space before yielding metadata.
- `expand=space,version` is an additive M5B-2 scope-correctness requirement, not
  a request shape observed in M5B-0; M5C must confirm it in the live smoke run.
- Keep the strict root-space postcondition inside the concrete adapter without a
  public parser strict-mode flag.
- Implement explicit root-page inclusion, root-scoped CQL, and enough validated
  numeric pagination for inventory correctness using the M5B-1 parser.
- Use a standard-library HTTPS JSON transport with explicit timeout and response
  size bounds, redirect refusal, and safe errors that omit response bodies,
  credentials, and deployment identifiers.
- Require an explicit finite `max_search_pages` request budget; permit
  `totalSize` drift and ignore `_links.next` while advancing from validated
  numeric envelope fields.
- Root labels remain optional enrichment and normalize to `()`; no extra root
  label request is made in M5B-2.
- Do not implement retries, rate limiting, checkpointing, or resume here.

### M5C-1 - Reviewed safe smoke runner

Status: implemented; independent review pending.

- Committed `foundation/cli/` entrypoint at
  `src/knowledgenexus/foundation/cli/confluence_inventory_smoke.py`, run as
  `python -m knowledgenexus.foundation.cli.confluence_inventory_smoke`.
- Placement follows D35 (`foundation/cli/` owns crawl/export jobs) and keeps D34
  intact: the runner is a composition root touching `foundation.infrastructure`,
  which `presentation` is not allowed to import. Under `foundation/cli/` it adds
  zero cross-context edges.
- Composes the approved transport, adapter, use case, and report writer only.
- Credentials come from `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT`; the PAT has
  no CLI flag and `.env` is never loaded.
- `--output-dir` is forced outside the repository and must be an existing empty
  directory; live reports never enter the repository.
- Verification reopens both reports from disk and counts CSV records with
  `csv.reader`, because real titles may contain commas, quotes, or newlines.
- `m5c_smoke_summary.json` is success-only and carries counts, booleans, limits,
  and hashes; failures emit one sanitized category to stderr.
- Root labels are not requested; an empty root labels value means "unknown", not
  "confirmed empty".
- Operator runbook: `docs/runbooks/M5C_CONFLUENCE_INVENTORY_SMOKE.md`.

### M5C-2 - Live inventory run on main machine

Status: planned after the M5C-1 review.

- Run one real space/root scope without a full page-content crawl.
- Use the small M5B-0 test root with `page_size = 2` and
  `max_search_pages = 10`. Do not use the large production root; a
  `pagination_limit` exit means the chosen root is too large for a smoke run.
- First live confirmation of the additive `expand=space,version` root request.
- Inspect the deterministic report and choose exact excluded subtrees before
  M6, using explicit page IDs rather than root labels.
- Preserve secrets outside committed configuration and artifacts. Copy back only
  the safe summary and a manually sanitized completion notice.

M5 completion gate:
- M5A mocked inventory and reports remain deterministic.
- M5B basic pagination terminates correctly against confirmed sanitized API
  fixtures.
- M5C produces a manually reviewed small real inventory without page-body or
  attachment download.

## 8. M6 - One-Page Real Foundation Vertical Slice

Purpose:
Prove one real page can move through the entire Foundation boundary before
scaling horizontally.

Status:
- M6-0 operator page-fetch live evidence: done and approved on the primary
  machine; the sanitized conclusion is registered in `IMPLEMENTATION_STATE.md`
  and `.local_ai/review/m6-0-confluence-page-fetch-evidence-summary.md`. It
  confirms the page, view-restriction, and attachment request shapes. No raw
  artifact is stored in the repo, by sanitization design.
- M6A: next; implementation not started.
- M6B-M6G: planned.

Tasks:
- M6-0 confirm live page/restriction/attachment request shapes (done).
- M6A fetch and preserve one raw page (page request only).
- M6B capture restrictions and attachment metadata.
- M6C normalize one page and produce `CanonicalDocument`.
- M6D chunk one normalized page and produce `ChunkRecord`s.
- M6E extract one relation path and produce `RelationRecord`s.
- M6F materialize deny-safe ACL and propagate ACL tags to chunks.
- M6G export one-page real snapshot through M3.

Completion gate:
- One real page has raw provenance.
- One `CanonicalDocument` is valid.
- Chunks are valid and stable.
- ACL is deny-safe.
- Relations are valid.
- Final one-page snapshot validates end to end.

## 9. M7 - Crawl Reliability and Scale

Purpose:
Scale the proven vertical slice without changing contract semantics.

Responsibilities:
- Pagination hardening beyond M5B correctness behavior.
- Rate limiter.
- `Retry-After` support.
- Exponential backoff.
- Checkpointing.
- Resumability.
- Per-page/per-attachment progress.
- Incremental inventory comparison.
- Error isolation and reporting.
- No secrets in logs.

Completion gate:
- Interrupted crawl resumes correctly.
- Retries are bounded.
- Rate limits are respected.
- Unchanged pages can be skipped using version/hash signals where contract
  specifies.
- Failures are represented in quality/reporting state.

## 10. M8 - Production-Quality Normalization and Chunking

Purpose:
Expand the one-page implementation into complete structure-aware processing.

Normalization scope:
- Headings, paragraphs, tables, fenced code blocks.
- Confluence macros.
- Include/excerpt placeholders.
- Draw.io/media placeholders.
- Unknown macro fallback.
- No silent meaningful-text loss.

Chunking scope:
- Wiki heading sections.
- Breadcrumbs.
- Table row groups.
- Fenced code blocks.
- Oversize splitting.
- Controlled overlap.
- Deterministic token counts.
- Stable chunk IDs.
- Produce a deterministic complete chunk set for one document.
- Expose enough IDs/hashes for a later update-propagation layer.

Completion gate:
- Unchanged input produces byte-identical chunks.
- Oversized units respect hard limits.
- All omissions are policy-driven or reported.
- Chunk text used for hash/ID is exactly the exported text.
- No downstream embedding mutation is needed.

## 11. M9 - Media, Git, Symbols, and Deletion Propagation

Split this milestone into independent tracks.

M9A - Media:
- Attachment inventory.
- Metadata-first processing.
- Draw.io parse where possible.
- PDF text extraction.
- OCR for selected images.
- Video deferred.
- Activate `MediaAssetRecordBuilder` here if deferred.
- Inherit parent ACL deny-safely.

M9B - Git repository scan:
- Configured repository and branch.
- Source-file inventory.
- Exclude generated/vendor/build/binary paths.
- Preserve commit hash and file provenance.
- Create `CanonicalDocument` and `ChunkRecord` for code files.

M9C - Symbol index:
- Activate `SymbolIdGenerator`.
- Activate `SymbolRecordBuilder`.
- Tree-sitter parser for agreed languages.
- Line ranges valid at commit hash.
- Deterministic overload handling.
- No full call graph.

M9D - Tombstones and delta/update propagation:
- Activate `TombstoneRecordBuilder` if deferred.
- Inventory diff.
- Compare previous and current document/chunk state.
- Apply content-hash unchanged short-circuit.
- Diff previous and current chunk-ID sets.
- Emit tombstones for disappeared chunk IDs.
- `source_deleted`, `access_revoked`, `moved_out_of_scope`,
  `content_updated`, `config_invalidated`.
- Cascade semantics.
- Delta snapshot behavior.
- This track does not block the initial full snapshot. Real tombstone/delta
  behavior is required before the second sync or first delta export.

M9 completion gate:
- Each track has focused tests.
- Media and code records preserve provenance and ACL.
- Symbol references resolve to valid chunks.
- Tombstones identify exact entity types.
- No Foundation code directly writes to Qdrant or Indexing storage.

## 12. M10 - First Full POC Foundation Snapshot

Purpose:
Produce the first complete contract-valid Foundation dataset for the agreed
Confluence scope and configured Git branch.

Expected contents, subject to the active Foundation export contract:
- `documents.jsonl`
- `chunks.jsonl`
- `relations.jsonl`
- `acl.jsonl`
- `media_assets.jsonl`
- `symbols.jsonl`
- `sync_state.jsonl`
- `tombstones.jsonl`
- `manifest.json`
- `quality_report.md`
- `LATEST.txt` at the dataset root

Acceptance categories:
- Scope: include root and exclusions applied correctly.
- Raw preservation: processed sources have auditable raw provenance.
- Normalization: meaningful content is retained or explicitly reported.
- Chunking: deterministic and contract-valid.
- ACL: every chunk has non-empty deny-safe `acl_tags`.
- Relations: Jira/page/media/code relations validate.
- Media: expensive processing follows policy.
- Symbols: configured languages produce minimal symbol records.
- Export: full snapshot passes schema validation, folder/manifest version
  handshake passes, counts match, and `LATEST.txt` points to the completed
  snapshot.
- Security: no PAT/token values in config, logs, reports, or exports.
- Boundary: no embedding, no Qdrant, no retrieval, no chat, no Gauss.

## 13. Immediate Execution Order

1. M5C run and manually review one small real inventory.
2. M6 prove the first real page content vertical slice.
3. M7 add crawl reliability before scaling inventory/content collection.

### Completed task - M2C3 RelationRecordBuilder

Objective:
- Build schema-shaped `RelationRecord` dictionaries.

Schema/files to inspect:
- `contracts/foundation/schemas/relation_record.schema.json`
- `contracts/foundation/schemas/defs.schema.json`
- `src/knowledgenexus/foundation/domain/rules/relation_id_generator.py`

Scope:
- One builder file, export update if needed, focused tests.
- Optional field policy must be schema-driven.

Out of scope:
- Extraction, discovery, hydration, graph expansion, external calls.

Expected tests:
- Valid Jira relation.
- Valid non-Jira relation if supported by schema.
- Optional `evidence`/`confidence` behavior.
- Invalid required inputs.
- Schema validation.

Acceptance:
- Existing suites still pass.
- Built records validate.
- No optional schema field is made required accidentally.

Likely review artifact:
- `.local_ai/review/m2c3-relation-record-builder-review-summary.md`

### Completed task - M2C4 ACLRecordBuilder

Objective:
- Build schema-shaped `ACLRecord` dictionaries.

Schema/files to inspect:
- `contracts/foundation/schemas/acl_record.schema.json`
- `contracts/foundation/schemas/defs.schema.json`
- `src/knowledgenexus/foundation/domain/rules/acl_id_generator.py`

Scope:
- One builder file, export update if needed, focused tests.
- Copy all retained list inputs.

Out of scope:
- Fetching Confluence restrictions.
- Group expansion.
- Query-time authorization.
- Connector work.

Expected tests:
- Unrestricted sample.
- Restricted sample.
- Unresolved/default-deny sample.
- Empty `acl_tags` fails where schema forbids it.
- Schema validation.

Acceptance:
- Built records validate.
- `acl_tags` never empty.
- No resolver or connector behavior appears.

Likely review artifact:
- `.local_ai/review/m2c4-acl-record-builder-review-summary.md`

### Completed task - M2C5 Builder Review Gate

Objective:
- Decide which remaining builders must exist before M2D/M3/M4.

Schema/files to inspect:
- `media_asset.schema.json`
- `sync_state_record.schema.json`
- `tombstone_record.schema.json`
- `symbol_record.schema.json`
- Active M2D/M3/M4 requirements.

Scope:
- Documentation/review decision only unless a focused builder is activated.

Out of scope:
- Implementing all deferred builders automatically.

Expected tests:
- None for a documentation-only gate.

Acceptance:
- Each deferred builder has a reason, activation milestone, and dependency.

Likely review artifact:
- `.local_ai/review/m2c5-builder-gate-review-summary.md`

### Completed task - M2D Coherent Contract Sample Set

Objective:
- Build a tiny deterministic in-memory sample graph using the existing document,
  chunk, relation, and ACL builders.

Scope:
- Test fixtures/factories only.
- Cross-record invariant tests.
- Schema validation through `FoundationSchemaValidator`.

Out of scope:
- JSONL writing.
- Manifest generation.
- Export snapshot filesystem layout.
- Real source ingestion.
- Embedding, indexing, retrieval, chat, or Qdrant.

Acceptance:
- All sample records validate.
- Cross-record references are consistent.
- Sample IDs are deterministic and unique.
- Fixture data is small and reusable by M3 exporter tests.

Likely review artifact:
- `.local_ai/review/m2d-sample-record-set-review-summary.md`

### Completed task - M3A JsonlRecordWriter

Objective:
- Write caller-provided JSON-compatible records as deterministic JSONL.

Scope:
- Low-level writer only.
- Preserve caller-provided order.
- Deterministic UTF-8 output and newline behavior.
- No schema loading or Foundation contract validation inside the writer.

Out of scope:
- Snapshot directory layout.
- Manifest generation.
- Record counting beyond simple write behavior.
- `LATEST.txt`.
- Export orchestration.
- Real source ingestion.

Acceptance:
- One record writes one line.
- Multiple records preserve order.
- Unicode round-trips as UTF-8 JSON.
- Deterministic inputs produce deterministic bytes.

Likely review artifact:
- `.local_ai/review/m3a-jsonl-record-writer-review-summary.md`

### Completed task - M3B DatasetVersionGenerator

Objective:
- Define and implement the producer-side Foundation `dataset_version`
  convention.

Scope:
- Pure deterministic domain rule.
- Caller supplies a timezone-aware `datetime`.
- Convert to UTC and format as `vYYYYMMDD-HHMMSS-ffffffZ`.
- Consumers treat `dataset_version` as opaque; the required handoff invariant is
  equality between folder name, `manifest.dataset_version`, and `LATEST.txt`.

Out of scope:
- Manifest generation.
- Snapshot directory layout.
- LATEST.txt.
- ClockPort.
- Export orchestration.

Acceptance:
- Same instant produces same output.
- Equivalent instants with different offsets produce the same output.
- Naive datetimes are rejected.
- Non-datetime inputs are rejected.

Review artifact:
- `.local_ai/review/m3b-dataset-version-generator-review-summary.md`

### Completed task - M3C ManifestRecordBuilder

Objective:
- Build schema-shaped `Manifest` dictionaries according to the active manifest
  schema.

Scope:
- Plain JSON-compatible dict builder.
- Caller-provided counts/config/export metadata.
- Schema validation in tests.
- `counts` copied into a plain dict.
- `source_scopes` deep-copied into a plain top-level dict.

Out of scope:
- Filesystem scanning.
- JSONL writing.
- Snapshot directory layout.
- LATEST.txt.
- Delta ordering or previous snapshot lookup.

Review artifact:
- `.local_ai/review/m3c-manifest-record-builder-review-summary.md`

### Completed task - M3D machine-readable staging

Objective:
- Build and validate the eight JSONL files plus `manifest.json` in an owned
  staging directory.

Review artifact:
- `.local_ai/review/m3d-full-snapshot-staging-writer-review-summary.md`

### Completed task - M3E quality report / contract-complete staging

Objective:
- Add deterministic `quality_report.md` to an existing successful M3D staging
  directory and verify the exact complete ten-file set.

Scope:
- Load and validate the existing Manifest.
- Enforce full-snapshot producer invariants.
- Render Manifest metadata, fixed-order counts, and performed completion checks.
- Preserve the M3D files and own only M3E-created report artifacts.

Review artifact:
- `.local_ai/review/m3e-full-snapshot-staging-completer-review-summary.md`

### Completed task - M3F atomic finalize + LATEST.txt

Objective:
- Atomically rename a verified contract-complete staging directory into its
  final dataset-version path, then update `LATEST.txt` last.

Scope:
- Require staging to be a direct non-symlink child of the existing dataset root.
- Revalidate the completed ten-file set, Manifest, full-snapshot invariants, and
  M3B dataset-version shape before publication.
- Reject every pre-existing final destination entry.
- Publish by direct same-parent directory rename without a copy fallback.
- Atomically replace `LATEST.txt` from a same-directory temporary file only
  after the final snapshot exists.
- Preserve an unadvertised final snapshot if pointer update fails; no automatic
  rollback or recovery.

Review artifact:
- `.local_ai/review/m3f-full-snapshot-publisher-review-summary.md`

Deferred after M3F:
- Rich POC quality metrics without actual producer evidence.
- Snapshot overwrite or replacement policy beyond the approved initial publish.
- Delta publication and previous-snapshot lookup.
- Locking and crash-recovery journals.
- Real connectors.
- Real source ingestion.
- Embedding/indexing/retrieval/chat.

M3 result:
- Full-snapshot export construction, completion, atomic publication, and
  `LATEST.txt` advertisement are implemented and fixture-tested.
- Proceed to M4 golden sample export.

## 14. Review Gates

Gate A - Minimum record-builder gate:
Before starting M2D:
- `CanonicalDocumentRecordBuilder` exists.
- `ChunkRecordBuilder` exists.
- `RelationRecordBuilder` exists.
- `ACLRecordBuilder` exists.
- Focused schema-validation tests pass.
- No builder performs exporter, connector, extraction, or chunking work.

Gate B - Contract graph gate:
Before M3:
- A coherent Document + Chunk + Relation + ACL sample set exists.
- All records validate.
- Cross-record IDs and references are consistent.

Gate C - Export gate:
Before real connectors:
- Fixture-backed full snapshot validates.
- Manifest/count/`LATEST.txt` behavior is safe.
- Failed exports do not publish partial snapshots.

Gate D - Vertical-slice gate:
Before scaling crawl:
- One real page completes raw -> normalize -> chunk -> ACL/relation -> export.

Gate E - Scale gate:
Before full POC:
- Rate limit, retry, checkpoint, and resume are proven.

## 15. Backlog and Deferred Items

| Item | Deferred until | Reason | Activation condition |
|---|---|---|---|
| `SymbolIdGenerator` | Symbol indexer | Symbol identity depends on parser/symbol semantics. | M9C starts. |
| `SymbolRecordBuilder` | Symbol indexer | Avoid inventing semantics before parser output exists. | M9C starts or a contract fixture explicitly requires it. |
| `DatasetVersionGenerator` | done in M3B | Directly required by export snapshot layout. | Implemented as pure domain rule. |
| Timestamp formatting helper | Exporter/clock boundary | Builders currently accept schema-facing strings. | M3B or a real clock boundary task. |
| SourceType enum | Typed domain model requirement | Schemas remain authoritative and builders are schema-facing. | A typed domain model milestone is approved. |
| `SyncStateRecordBuilder` | Checkpoint/crawler flow unless M4 requires it | Exported sync state depends on actual job/checkpoint semantics. | Crawler/checkpoint flow exists or sample export needs a representative record. |
| `TombstoneRecordBuilder` | Delta/update propagation unless fixtures require it | Real tombstones depend on deletion/update semantics. | M9D starts or representative contract fixtures require it. |
| `MediaAssetRecordBuilder` | M4 sample requirements or media work | Avoid fake media semantics before media policy is active. | M4 needs non-empty media or M9A starts. |
| Query-time ACL resolver | Out of Foundation scope | Retrieval/platform permission concern. | Retrieval/platform ACL task. |
| Embedding/Qdrant | Out of Foundation scope | Owned by Indexing. | Indexing snapshot importer/indexer task. |
| Retrieval/chat/Gauss | Out of Foundation scope | Owned by Retrieval/Chat. | Retrieval/chat milestones. |

## 16. Roadmap Maintenance Rules

- Update `ROADMAP.md` only when milestone ordering, scope, or gates change.
- Update `IMPLEMENTATION_STATE.md` when implementation status changes.
- Do not duplicate full schemas or normative constants in this roadmap.
- Link to schema/contract paths instead of copying long field lists.
- Mark tasks done only with repository/test evidence.
- Keep at most the next 2-3 tasks implementation-detailed.
- Keep later milestones directional to avoid stale speculative design.
- Record schema conflicts in the relevant review summary.
- Do not convert deferred items into active tasks without documenting the
  dependency that activated them.
- One Codex task should implement one concept.
- Do not create future folders merely because this roadmap mentions them.
