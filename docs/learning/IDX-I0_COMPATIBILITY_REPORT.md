# IDX-I0 Foundation-to-Indexing Compatibility Report

Status: **review**

This document supersedes the draft committed as `9351d60`. It replaces that
draft's incomplete planning basis with the approved handoff plan, Foundation
contracts, current Foundation producer, read-only Indexing bundle, and RET-R2
constraints. It authorizes no production work.

## Scope and evidence rules

Reviewed: plan, specified roadmap sections and naming rules; all Foundation
schemas and contract documents; specified Foundation writer/completer/publisher
and shared validator/loader; the complete read-only Indexing tree in the bundle;
both Qdrant configurations; specified RET-R2/search documents. No runtime data,
credentials, live capture, network service, or Foundation-to-Indexing direct
chunk-write endpoint was used.

The report uses repository-relative source paths and line citations only. It
contains no snapshot content, source identifiers, local artifact paths,
credentials, or full artifact hashes.

## Draft reconciliation

The superseded draft is corrected as follows.

| Draft issue | Corrected I0 position |
|---|---|
| Called the snapshot ten files. | D12 requires an eleventh regular `digest-set` member. The current producer still makes ten complete files, so D12 must update every exact-file gate before I1. |
| Required resolver support for `LATEST.txt`. | Destination and event-triggered imports use explicit version plus two digests. `use_latest` is only a local Foundation/fixture inspection option; D3/D11 prohibit it at the destination. |
| Treated `sync_state.jsonl` as an optional diagnostic. | It is one of the eight mandatory JSONL streams written and counted by the Foundation producer. |
| Omitted D9, D12, D13, and B1. | D9 status/acknowledgement, D12 integrity/dataset identity, D13 activation/delta recovery, and B1 delivery bridge are now explicit prerequisites and owners. |

The following findings from the draft remain verified: Foundation `chunk_id` is
a string while the existing Qdrant mapping is UUID-oriented; the current Qdrant
payload lacks ACL/filter and dataset provenance/version isolation;
`ChunkStorageService` writes directly to live stores and is not an I2 commit
boundary; and SQLite lacks relation/ACL/symbol/media/tombstone/dataset-version
coverage and a two-store activation barrier.

## Authoritative snapshot contract and current producer

The precedence order is schemas, `CHUNKING_SPEC.md`, integration contract,
decision log, then `START_HERE.md` (handoff plan section 3; `START_HERE.md:14`).
Foundation produces `manifest.json` plus eight required JSONL streams:
documents, chunks, relations, ACL, media assets, symbols, sync state, and
tombstones (`full_snapshot_staging_writer.py:20`). The writer's machine set is
nine files (`:31`); the completer adds `quality_report.md` to make the current
ten-file complete set (`full_snapshot_staging_completer.py:31-42`).
`sync_state.jsonl` is therefore mandatory in the writer and manifest counts,
not an Indexing-optional file.

D12 changes the final delivered version to eleven files: the existing ten plus
the digest-set written last. It lists the ten other members and their byte sizes
and SHA-256 values, but not itself. Current exact-set gates reject it in the
writer (`full_snapshot_staging_writer.py:174-186`), completer
(`full_snapshot_staging_completer.py:631-643`), and publisher
(`full_snapshot_publisher.py:100-112`). The current manifest has no
`dataset_name` or member digest binding (`manifest.schema.json:7-58`). D12 must
choose a versioned manifest identity or trusted transport namespace and must set
the old-snapshot re-export/compatibility policy.

The lower-precedence integration contract's historical wording allowing
`LATEST.txt` and calling sync-state diagnostic (`Task2_Task3_Integration_Contract.md:36-41`,
`:175-183`) is superseded by D3/D11/D12. In particular, destination/event
imports bind an explicit version, manifest digest, and digest-set digest; they
must never infer a version from destination `LATEST.txt`.

## Compatibility matrix

Unless stated otherwise, every short Indexing citation in this matrix and the
gap list is relative to the read-only bundle directory
`KnowledgeNexus/KnowledgeNexus/src/knowledgenexus/`; Qdrant configuration is
relative to `KnowledgeNexus/KnowledgeNexus/config/`. The parent directories and
line ranges are therefore part of every cited path.

| Area | State | Evidence and required owner |
|---|---|---|
| Snapshot resolver | Partial | `snapshot_resolver.py:57-91` resolves explicit/latest and validates layout; I1 owns immutable explicit-version resolver after D12/B1. |
| Strict manifest/JSONL validation | Partial | Resolver parses manifest at `snapshot_resolver.py:80-90`; streams use shared validator at `schema_validator.py:89-129`. I1 adds strict duplicate-key/non-finite rejection, digest, bounds, and verified-byte ownership. |
| Full import | Not present | No `ImportFoundationSnapshot` application composition exists in the Indexing tree; I2-B owns it. |
| Delta import | Not present | Only resolver stream-name mapping at `snapshot_resolver.py:21-38`; no mode/base/tombstone behavior. I2-C owns it after D13 and retention. |
| Ingest job/idempotency storage | Partial | Status model `ingest_job.py:8-23` and repository `sqlite_ingest_job_repo.py:15-39`; no dataset/version/digest identity at `database/models.py:41-50`. I2-A/B own it. |
| Document/chunk repositories and hydrate text | Partial | SQLite document/chunk repos exist (`sqlite_document_repo.py:17-79`, `sqlite_chunk_repo.py:18-100`) and chunk text is stored (`database/models.py:26-38`); UUID-shaped identity conflicts with Foundation strings (`database/models.py:16,30`, `mappers.py:25-36,72-87`). I2-A owns migration. |
| Relation/ACL/media/symbol repositories | Not present | Database models contain only Document, Chunk, and IngestJob (`database/models.py:12-50`); no matching repository/port in the bundle. I2-A owns it. |
| Tombstone by entity type | Not present | Resolver recognizes a tombstone stream (`snapshot_resolver.py:37`), but no application implementation exists. I2-C owns all six schema entity types. |
| BGE-M3 document embedding | Partial | Batch BAAI/bge-m3, 1024 dimensions, normalization exist (`bge_m3_embedder.py:12-18,87-105`); no importer invokes it. I2-B owns verbatim document embedding. |
| Deterministic Qdrant IDs | Not present / incompatible | `_to_point_id` accepts UUID only (`qdrant_store.py:32-37`), while Foundation chunk IDs are strings (`defs.schema.json:42-45`). I2-A owns D6 UUIDv5 mapping. |
| Slim payload and payload indexes | Partial / incompatible | Payload has six keys (`qdrant_store.py:40-52`) and config indexes only five fields (`config/qdrant.collection.yaml:1-15`). I2-A adds required ACL, provenance, dataset/version, and indexes. |
| Staging and activation | Not present | Qdrant targets one configured collection (`qdrant_store.py:165-244`); SQLite writes commit immediately (`sqlite_chunk_repo.py:21-47`, `sqlite_document_repo.py:19-40`). I2-A/I3 own staged references and D13 ledger. |
| Retry/recovery | Not present | Jobs only expose PENDING/RUNNING/COMPLETED/FAILED (`ingest_job.py:8-13`); no resumable recovery implementation. B1, I2-B, I3, and I4 own their respective recovery paths. |
| API/CLI composition | Partial, prohibited as handoff | Direct `POST /api/v1/store/chunks` writes chunks (`presentation/api/v1/store.py:20-55`); no snapshot-import CLI/API composition. This endpoint must not be the Foundation handoff; I2-B/I4-B own approved boundaries. |
| Dependency-boundary tests | Partial | Resolver/vector/repository/embedder tests exist, e.g. `tests/indexing/infrastructure/importers/test_snapshot_resolver.py:15-63`; current architecture test is Foundation-internal only (`tests/architecture/test_application_import_boundary.py:8-50`). I1-I4 add Indexing-to-Foundation isolation tests. |
| Database migrations | Not present (explicit absence finding) | No Alembic/migration tree exists; bootstrap calls `Base.metadata.create_all` (`database/engine.py:43-45`). I2-A owns reviewed migration/rollback design. |

## Verified gaps and ownership

### P0

1. The resolver's `_REQUIRED_FILES` hard-codes the old ten-file inventory
   (`snapshot_resolver.py:17-28`) and rejects every unexpected entry
   (`:109-120`). D12's digest-set would fail every snapshot until D12 updates
   the producer and I1 replaces the consumer inventory rule.
2. Qdrant treats `chunk_id` as a UUID (`qdrant_store.py:32-37`), but Foundation
   defines a non-UUID string grammar (`defs.schema.json:42-45`). I2-A must keep
   the original string identity and calculate `uuidv5(POINT_ID_NAMESPACE,
   chunk_id)`.
3. The slim payload omits `dataset_name`, `dataset_version`, `source_system`,
   `content_kind`, `language`, `chunker_version`, `embedding_model`,
   `config_hash`, and `acl_tags` (`qdrant_store.py:40-52`). I2-A must add the
   approved slim deny-safe payload and payload indexes before writes.
4. Resolver trust is insufficient: `resolve(None)` reads `LATEST.txt`
   (`snapshot_resolver.py:68-73`); parsing uses bare `json.loads`
   (`snapshot_resolver.py:80-84`, `schema_validator.py:99-129`); checks are
   symlink-only (`snapshot_resolver.py:77,95,119`); and no digest, byte/record
   limit, verified copy/handle, or TOCTOU binding exists. I1 must fail closed
   before parse/mutation after D12/B1.
5. D12 has no current producer implementation: exact gates permit only the
   current ten complete files (`full_snapshot_staging_completer.py:42`,
   `full_snapshot_publisher.py:100-112`). D12 must version the contract and
   add digest generation/verification before B1/I1.

### P1

1. One fixed collection is configured (`config/qdrant.collection.yaml:1`), and
   Qdrant creates/uses that one name (`qdrant_store.py:165-203`). There is no
   versioned collection, alias, or application activation ledger. I2-A/I3 own
   D13's staged version and sole reader gate.
2. `ChunkStorageService` writes SQLite then Qdrant directly
   (`chunk_storage_service.py:24-34`), so it cannot be I2's commit boundary.
   I2-B must use staged injected ports and I3 must activate only after two-store
   verification.
3. SQLite is incomplete for Foundation entities, provenance/version isolation,
   and activation, with no migration mechanism (`database/models.py:12-50`,
   `database/engine.py:43-45`). I2-A owns the migration and rollback design.

### P2

1. The shared schema validator is useful but its JSONL parser is not strict
   against duplicate keys or non-finite constants (`schema_validator.py:99-102`).
   I1 must add an Indexing-owned strict input parser without importing
   Foundation Python modules.
2. Current tests do not prove the required cross-context dependency boundary or
   public-boundary malformed-input behavior. I1-I4 must test `object()`,
   `None`, wrong enums, missing/extra fields, and impossible typed counters
   before field access or side effects.

## RET-R2 forward-compatibility input (owner decision)

D12 currently describes the digest-set as a fixed eleventh file and requires I1
to reject any other inventory (handoff plan:209-232). RET-R2 needs a future
hydrate-only structure stream and migration across manifest, resolver,
importer, delta/tombstone, rollback, and activation
(`RET-R2_IMPLEMENTATION_PLAN.md:122-144`). Therefore a resolver with a fixed
eleven-name set would require a second resolver migration when the structure
stream arrives.

Recommended decision input, not an I0 decision: make the digest-set the member
inventory source of truth; require actual members to equal digest-set entries
plus the digest-set itself; and constrain permitted filenames/streams by
`schema_version`. This preserves strict rejection while making a versioned
structure-stream addition an inventory/schema extension rather than another
hard-coded file-count migration.

The owner should also decide whether the RET-R2 structure stream belongs in the
same D12 schema bump. Combining can avoid two migrations but broadens and may
delay D12/I1; separating requires the explicit compatibility window, full
re-export/re-index, and rollback plan called for by RET-R2. I0 does not choose
either option.

## Decisions and stop condition

Before any implementation, the owner must answer:

1. Use `[HANDOFF-I1]` commit tags as the handoff plan shows, or `IDX-I1` as
   roadmap naming rules require?
2. By what mechanism, and at what post-W5-D frozen head, is the Indexing base
   imported into the primary repository? The inspected bundle's short planning
   head is `203b599`; it is not an implementation authorization.
3. For pre-D12 ten-file snapshots without digest-set, require re-export or
   allow a bounded controlled compatibility flag?

I0 stops here. W5-B/W5-C have not run, so all subsequent work risks rebase
after the post-W5-D freeze. D12 and D13 remain owner decisions; B1, I1, and all
production changes require a new authorization and a fresh independent I0
review before the I1 scope is frozen.
