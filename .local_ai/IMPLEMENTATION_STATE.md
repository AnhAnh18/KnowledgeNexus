# Implementation State

## Current Milestone

The current priority is Confluence closeout. PLM M11 is explicitly held until
the remaining real Confluence gates are completed and the required sanitized
PLM MCP evidence is available.

M6 is complete and approved. M7-C durable crawl implementation is complete
through C4-B and has an integrated correctness path. The M7-C5 inventory
durability slice is now complete and independently reviewed `PASS`; the
10k correctness baseline and C5-B1 validation fast path remain approved,
while the 100k scale gate is incomplete and performance optimization is
deferred. The owner now accepts the bounded M7 stages as complete, with the
100k gate retained as a separate deferred follow-up. M7-D3 is complete and
independently reviewed as an offline, generation-scoped raw-page store. The
owner has authorized and accepted the bounded M7 roadmap stages. M7-D4-A
raw-page orphan inspection and M7-D4-B
restriction-evidence orphan inspection are complete, each independently
reviewed `PASS`; M7-D5-A raw-page replay/checkpoint integration and M7-D5-B
restriction-evidence replay are complete and independently reviewed `PASS`.
These stages do not imply a closed 100k scale gate. No
raw production artifact or published snapshot exists in this repository.
M8-A normalization fidelity and layout semantics, M8-B complex-table
migration, M8-C macro/placeholder/reference intents, M8-D generation-bound
page-set processing, and M8-E chunk-stability handoff are complete and
independently reviewed `PASS`. M8-AC controlled mini-corpus acceptance is
implemented and independently re-reviewed `PASS`; the operator has now run
the approved real mini-corpus and supplied the acceptance/chunk handoff.
M9-A1 metadata-first media contract is also
complete and independently reviewed `PASS`; M9-A1 and M9-A2 are complete and
independently reviewed `PASS`; M9-A3 is also independently reviewed `PASS`.
M9-B and M9-C are now independently approved. M9-D1 tombstone contract and
explicit cascade, and M9-D2 delta/inventory diff propagation, are independently
reviewed `PASS`. M9-D2 remains a read-only deterministic tombstone seam with no
export/store/checkpoint side effects. M10-A through M10-D are complete and
independently reviewed `PASS`. M10-E synthetic acceptance is complete and
independently reviewed `PASS`; no real full-snapshot run has started. OCR,
media, M10, second-sync, and scale evidence remain external gates.

## Confluence-First Execution Priority

- Reuse the operator-supplied M8-AC acceptance/chunk handoff; no second M8
  crawl is required unless the source generation changes.
- Complete the M9-A4 OCR productionization decision before enabling any OCR
  engine in the production path.
- Run the bounded real M10 full-snapshot acceptance for the agreed Confluence/
  Git scope and record its sanitized outcome.
- Keep PLM M11 on hold. Do not build a PLM adapter, crawler, or response model
  until sanitized read-only MCP fixtures prove the actual API contract.

## Durable State Convention

Milestone IDs and gate outcomes are authoritative. Commit SHAs appearing in
older historical notes are non-authoritative repository-local audit references
and may not exist in an independent patch-transfer repository. Current SHA
mappings belong only in the gitignored `.local_ai/LOCAL_PROVENANCE.md`.

## Done

- Ensured `src/knowledgenexus/__init__.py` exists.
- Ensured `src/knowledgenexus/foundation/__init__.py` exists.
- Added `src/knowledgenexus/shared/__init__.py`.
- Added `src/knowledgenexus/shared/contracts/foundation/__init__.py`.
- Added `tests/shared/contracts/foundation/` with `.gitkeep`.
- Added `.env.example` with empty placeholders.
- Updated `.gitignore` for local secrets, runtime data, bundles, and IDE files.
- Reshaped Foundation contract root to `contracts/foundation/`.
- Moved Foundation schemas to `contracts/foundation/schemas/`.
- Moved legacy decision logs to `contracts/foundation/decision_logs/`.
- Added `src/knowledgenexus/shared/contracts/foundation/contract_loader.py`.
- Added `src/knowledgenexus/shared/contracts/foundation/schema_validator.py`.
- Added schema validator tests under `tests/shared/contracts/foundation/`.
- Added valid JSONL count coverage for `validate_jsonl_file`.
- Added `src/knowledgenexus/foundation/domain/rules/content_hasher.py`.
- Added focused ContentHasher tests under `tests/foundation/domain/rules/`.
- Renamed the legacy contract root to `contracts/foundation/`.
- Renamed the shared validator package to `shared/contracts/foundation`.
- Renamed public shared validator symbols to `Foundation*`.
- Moved schema validator tests to `tests/shared/contracts/foundation/`.
- Added `src/knowledgenexus/foundation/domain/rules/text_normalization.py`.
- Added focused TextNormalizationRules tests under `tests/foundation/domain/rules/`.
- Added `src/knowledgenexus/foundation/domain/rules/chunk_id_generator.py`.
- Added focused ChunkIdGenerator tests under `tests/foundation/domain/rules/`.
- Added pipeline tests for TextNormalizationRules, ContentHasher, and ChunkIdGenerator.
- Added `src/knowledgenexus/foundation/domain/rules/relation_id_generator.py`.
- Added focused RelationIdGenerator tests under `tests/foundation/domain/rules/`.
- Added `src/knowledgenexus/foundation/domain/rules/acl_id_generator.py`.
- Added focused AclIdGenerator tests under `tests/foundation/domain/rules/`.
- Added `src/knowledgenexus/foundation/domain/rules/hashing_constants.py`.
- Updated content/relation/chunk hash code to use shared immutable hashing constants.
- Added `src/knowledgenexus/foundation/domain/rules/tombstone_id_generator.py`.
- Added focused TombstoneIdGenerator tests under `tests/foundation/domain/rules/`.
- Patched TombstoneIdGenerator tests to use contract-style reason examples.
- Added `src/knowledgenexus/foundation/domain/rules/document_id_generator.py`.
- Added focused DocumentIdGenerator tests under `tests/foundation/domain/rules/`.
- Added generic `DocumentIdGenerator.source_entity_id()` for future source entity IDs.
- M2B4 follow-up kept `DocumentIdGenerator.source_entity_id()` as a generic core helper, not a strategy layer.
- M2B4 review fix added coverage that `source_entity_id("github", "issue", "spen-sdk", "")` fails with `stable_parts[1]`.
- Added `src/knowledgenexus/foundation/domain/records/canonical_document_record_builder.py`.
- Added `src/knowledgenexus/foundation/domain/records/__init__.py`.
- Added focused CanonicalDocumentRecordBuilder tests under `tests/foundation/domain/records/`.
- Clarified CanonicalDocumentRecordBuilder input from `body_text` to `normalized_body_text`; empty normalized text is allowed and hashed.
- Patched CanonicalDocumentRecordBuilder review nits with `SCHEMA_VERSION` and list-copy coverage for `jira_keys`/`relation_ids`.
- Added `src/knowledgenexus/foundation/domain/records/chunk_record_builder.py`.
- Exported `ChunkRecordBuilder` from `src/knowledgenexus/foundation/domain/records/__init__.py`.
- Added focused ChunkRecordBuilder tests under `tests/foundation/domain/records/`.
- Implemented schema-shaped ChunkRecord dict construction with caller-supplied `chunk_id`, caller-supplied `token_count`, and `content_hash` computed from already-normalized `text`.
- M2C2 optional-field policy: omit absent optional fields, while defaulting `jira_keys` and `relation_ids` to empty lists because the schema allows them and downstream records benefit from stable list fields.
- Added `src/knowledgenexus/foundation/domain/records/relation_record_builder.py`.
- Exported `RelationRecordBuilder` from `src/knowledgenexus/foundation/domain/records/__init__.py`.
- Added focused RelationRecordBuilder tests under `tests/foundation/domain/records/`.
- Implemented schema-shaped RelationRecord dict construction with caller-supplied `relation_id`, schema-facing string fields, optional `evidence`, and optional `confidence`.
- M2C3 cleanup moved the shared Foundation record `schema_version` literal to `common_constants.py` as `SCHEMA_VERSION` and builders use it directly.
- Added `src/knowledgenexus/foundation/domain/records/acl_record_builder.py`.
- Exported `ACLRecordBuilder` from `src/knowledgenexus/foundation/domain/records/__init__.py`.
- Added focused ACLRecordBuilder tests under `tests/foundation/domain/records/`.
- Implemented schema-shaped ACLRecord dict construction with caller-supplied `acl_id`, caller-supplied final `acl_tags`, optional field omission, and copied list inputs.
- Completed M2C5 builder review gate.
- Deferred MediaAssetRecordBuilder, SyncStateRecordBuilder, TombstoneRecordBuilder, and SymbolRecordBuilder until their activating milestones/dependencies exist.
- Closed M2C and approved entry into M2D coherent contract sample set work.
- Added `tests/fixtures/foundation/record_factories.py`.
- Added `tests/fixtures/foundation/sample_record_set.py`.
- Added `tests/foundation/contracts/test_sample_record_set.py`.
- Implemented a deterministic in-memory Foundation sample graph with CanonicalDocument, ChunkRecord, RelationRecord, and ACLRecord records.
- Added schema-validation and cross-record invariant tests for the sample graph.
- Added coverage that M2D record factories delegate to the existing Foundation record builders.
- Added `src/knowledgenexus/foundation/infrastructure/exporters/jsonl_record_writer.py`.
- Added `tests/foundation/infrastructure/exporters/test_jsonl_record_writer.py`.
- Implemented `JsonlRecordWriter.write(*, path, records) -> int` for deterministic UTF-8 JSONL serialization.
- M3A JSON settings: `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, and `allow_nan=False`.
- M3A writer preserves caller-provided record order, writes `\n` line separators, emits a final newline for non-empty output, and creates a zero-byte file for empty input.
- M3A writer uses a same-directory temporary file and closes it before replacing the final target.
- M3A review fix materializes each `Mapping` record into a plain `dict` before JSON serialization, preserving the public `Mapping` API while still streaming one record at a time.
- M3A writer does not create parent directories, perform schema validation, generate manifests, create snapshot layout, or update `LATEST.txt`.
- Added `src/knowledgenexus/foundation/domain/rules/dataset_version_generator.py`.
- Exported `DatasetVersionGenerator` from `src/knowledgenexus/foundation/domain/rules/__init__.py`.
- Added `tests/foundation/domain/rules/test_dataset_version_generator.py`.
- M3B dataset_version convention is `vYYYYMMDD-HHMMSS-ffffffZ`.
- M3B clock boundary: caller supplies a timezone-aware `datetime`; the generator converts it to UTC and does not acquire current time.
- M3B generator rejects naive datetimes with `ValueError` and non-datetime inputs with `TypeError`.
- M3B producer-policy note: when a committed Foundation export-conventions decision log exists, record the `dataset_version` convention there; downstream still treats `dataset_version` as opaque and relies only on equality between folder name, `manifest.dataset_version`, and `LATEST.txt`.
- M3B did not add ClockPort, manifest generation, snapshot directories, `LATEST.txt`, schema changes, or contract changes.
- Added `src/knowledgenexus/foundation/domain/records/manifest_record_builder.py`.
- Exported `ManifestRecordBuilder` from `src/knowledgenexus/foundation/domain/records/__init__.py`.
- Added `tests/foundation/domain/records/test_manifest_record_builder.py`.
- M3C actual required Manifest fields: `schema_version`, `dataset_version`, `export_mode`, `generated_at`, `config_hash`, `chunker_version`, `schemas_version`, and `counts`.
- M3C actual optional Manifest fields: `base_dataset_version` and `source_scopes`.
- M3C `base_dataset_version` policy: omit when `None`; preserve caller-supplied strings exactly; delta semantic requirements remain a later orchestration responsibility.
- M3C `counts` policy: required caller-provided mapping, copied into a plain dict, arbitrary string keys, non-negative actual integer values, bool rejected.
- M3C `source_scopes` policy: optional caller-provided mapping, omitted when `None`, explicit `{}` preserved, top-level keys must be strings, deep-copied into a plain top-level dict.
- M3C discovered schema/validator nuance: `generated_at` has JSON Schema `format: date-time`, but the current validator setup did not reject a malformed date-time string during M3C tests, so M3C did not rely on that as a schema-boundary rejection assertion.
- M3C did not add file writing, snapshot orchestration, count generation, version generation, current-time acquisition, schema changes, or contract changes.
- M3C.1 resolved the schema/validator nuance: `FoundationSchemaValidator` now enforces JSON Schema `format: date-time` through the standard `jsonschema.FormatChecker` for both `validate_record()` and `validate_jsonl_file()`.
- M3C.1 declares `rfc3339-validator` in `requirements.txt` so `jsonschema.FormatChecker` has explicit RFC 3339 date-time support.
- M3C.1 operational follow-up is complete in the public `README.md`: it documents `python -m pip install -r requirements.txt`, the current unpinned dependency policy, and why `rfc3339-validator` is required for schema `format: date-time` enforcement.
- Added shared validator regression tests for valid Manifest date-times, fractional seconds, invalid arbitrary/date-only/calendar-invalid strings, JSONL date-time rejection, and RelationRecord `created_at` enforcement.
- Added `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_writer.py`.
- Exported `FullSnapshotStagingWriter` from `src/knowledgenexus/foundation/infrastructure/exporters/__init__.py`.
- Added `tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py`.
- M3D writes a machine-readable full-snapshot staging directory only; it does not publish/finalize the snapshot.
- M3D fixed JSONL file/schema mapping: `documents.jsonl` -> `CanonicalDocument`, `chunks.jsonl` -> `ChunkRecord`, `relations.jsonl` -> `RelationRecord`, `acl.jsonl` -> `ACLRecord`, `media_assets.jsonl` -> `MediaAsset`, `symbols.jsonl` -> `SymbolRecord`, `sync_state.jsonl` -> `SyncStateRecord`, and `tombstones.jsonl` -> `TombstoneRecord`.
- M3D count keys match JSONL basenames: `documents`, `chunks`, `relations`, `acl`, `media_assets`, `symbols`, `sync_state`, and `tombstones`; counts come from `JsonlRecordWriter` return values.
- M3D staging ownership policy: caller supplies a non-existing `staging_path`, parent must already exist, M3D creates/owns the staging directory, leaves it on success, and best-effort removes it on any post-creation failure without masking the original exception.
- M3D writes `manifest.json` as one deterministic strict JSON object after Manifest build and validation.
- M3D materializes each input `Mapping` record to a plain `dict` one record at a time before schema validation and JSONL writing, preserving the public generic-`Mapping` stream API without materializing full streams.
- M3D review cleanup verifies every direct child entry in staging, rejecting unexpected directories and symlinks instead of checking only regular-file names.
- M3D review cleanup added coverage for unexpected staging entries after manifest write and strict Manifest serialization failure cleanup.
- M3D intentionally defers final staging-to-snapshot publish, `LATEST.txt`, `quality_report.md`, delta export, locking, retry/recovery journals, and checksum behavior to later tasks.
- M3 sequencing correction: `quality_report.md` is required for a complete POC export, so staging must become contract-complete before any atomic finalize or `LATEST.txt` update.
- Added `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_completer.py`.
- Exported `FullSnapshotStagingCompleter` from the infrastructure exporters package.
- Added focused M3E tests under `tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py`.
- M3E accepts an existing successful M3D staging directory, requires the exact nine machine-readable files, loads `manifest.json` as one JSON object, and validates it through `FoundationSchemaValidator`.
- M3E full-snapshot producer invariants require `export_mode="full_snapshot"`, no `base_dataset_version`, exactly the eight approved count keys, and non-negative actual integer count values.
- M3E writes deterministic UTF-8 `quality_report.md` through a same-directory temporary file and verifies the final exact ten-file staging set.
- M3E owns only its temporary report file and the report created during the current operation; failures never delete staging, JSONL files, `manifest.json`, or unexpected caller-owned entries.
- M3E does not recount JSONL records, calculate quality metrics, publish or move staging, create `LATEST.txt`, add locking, or implement recovery.
- Active-contract difference: Master Spec v7.1 requires the final POC quality report to contain skips, failures, and coverage warnings. M3E intentionally emits only construction metadata and performed completion checks because those richer metrics do not yet exist; they remain deferred until real pipeline evidence is available and must not be invented.
- Added `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_publisher.py`.
- Exported `FullSnapshotPublisher` from the infrastructure exporters package.
- Added focused M3F tests under `tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py`.
- M3F public API is `FullSnapshotPublisher.publish(*, staging_path, dataset_root, validator) -> Path`.
- M3F requires an existing dataset root and an existing non-symlink staging directory that is a direct child of that root.
- M3F independently verifies the exact ten-file completed staging set, validates Manifest, enforces full-snapshot/count invariants, and requires the M3B `vYYYYMMDD-HHMMSS-ffffffZ` dataset-version shape before deriving a path.
- M3F derives `final_path` only as `dataset_root / manifest.dataset_version`, rejects every pre-existing final entry, and publishes using direct same-parent `Path.rename()` with no copy fallback.
- M3F writes `LATEST.txt` only after final publication, through a same-directory temporary file and atomic `Path.replace()`, with exact UTF-8 content `<dataset_version>\n`.
- Any failure before directory rename leaves staging and existing `LATEST.txt` unchanged. A failure after rename leaves the final snapshot intact and unadvertised while preserving the old pointer when replacement did not occur.
- M3F intentionally has no rollback, retry, recovery, locking, retention, overwrite, delta publication, or content-rewrite behavior.
- Known recovery boundary: an unadvertised final snapshot after `LATEST.txt` failure requires explicit operator action or a future focused recovery task; M3F never auto-promotes it.
- M3 full-snapshot export foundation is complete.
- Added `tests/fixtures/foundation/golden_record_set.py` with a fully synthetic deterministic record graph and a test-only M3D -> M3E -> M3F generation helper.
- Added `tests/foundation/integration/test_golden_full_snapshot_export.py` with seven focused end-to-end, contract-validity, determinism, serialized-coherence, and regression tests.
- Added the committed dataset-root fixture at `tests/fixtures/foundation/golden_full_snapshot/`.
- Added a scoped `.gitattributes` rule forcing LF checkout for golden fixture files so byte comparisons remain stable on Windows.
- M4 fixed metadata: dataset version `v20260714-000000-000000Z`, generated timestamp `2026-07-14T00:00:00.000000Z`, config hash `a` repeated 64 times, chunker version `1.2.0`, and schemas version `1.0`.
- M4 source scopes are synthetic: Confluence space `GOLDEN` and page ID `golden-page-001`; source-scope details remain absent from `quality_report.md`.
- M4 exact counts are documents 1, chunks 2, relations 1, acl 1, media_assets 1, symbols 0, sync_state 1, and tombstones 0.
- M4 golden dataset root contains `LATEST.txt` plus one fixed version directory containing the eight JSONL files, `manifest.json`, and `quality_report.md`; `symbols.jsonl` and `tombstones.jsonl` are zero bytes.
- The committed bytes were generated through the real M3D, M3E, and M3F pipeline. Normal tests generate only under `tmp_path` and never rewrite the committed fixture.
- M4 follows the M2D document/chunk/relation/ACL graph topology and production builders while replacing the older fixture identifiers/content with visibly synthetic `GOLDEN` values; Git/Symbol semantics remain deferred to M9.
- M4 wiki chunk text follows the active breadcrumb and fenced-code requirements; the same normalized text drives serialization, token-count fixture inputs, content hashes, and chunk IDs.
- M4 media identity uses `DocumentIdGenerator.confluence_attachment_id()` and the authoritative `confluence:attachment:<attachment_id>` convention.
- M4 exact-tree comparison checks relative entry kinds and byte equality, independently validates all records against the active schemas, recounts JSONL only in the acceptance test, runs coherence checks on deserialized committed JSONL, and proves two independent exports are byte-identical.
- M4 made no production-code or dependency changes and accessed no real source, network, environment credential, or user-specific data.
- The public `README.md` now reflects the Foundation-first repository, current package layout and M5 status, `pip`-based setup/test commands, the `rfc3339-validator` requirement, and the current unpinned-dependency policy.

## Current Constraints

Do not create or implement:
- Relation extraction
- RelationRecord model
- ACL extraction
- ACLRecord model
- permission resolver
- group/user expansion
- TombstoneRecord model
- tombstone policy
- document/chunk/relation/acl/media/symbol cascade behavior
- sync diff
- CanonicalDocument model
- RawDocument model
- SymbolRecord model
- MediaAsset builder
- SymbolRecord builder
- Confluence API connector
- chunker
- exporter/importer
- Qdrant/SQLite code
- embedding code
- retrieval/chat/API behavior

Do not create unrelated bounded-context folders as part of future tasks. Some non-M0A bounded-context folders already existed before the M0A scaffold work; do not expand them unless a task asks for it.

M2B4 follow-up constraints:
- Keep `DocumentIdGenerator.source_entity_id()` as a generic core helper, not a strategy layer.
- Do not add strategy classes, a registry, or a parser.
- No need to change the no-stable-parts error message; that is a different case from an empty later stable part.

M2C1 final state includes the follow-up rename:
- Builder input is `normalized_body_text`, not `body_text`.
- `normalized_body_text` may be empty.

## Current Acceptance

- `import knowledgenexus` should work when Python can import from `src`.
- `import knowledgenexus.foundation` should work when Python can import from `src`.
- `import knowledgenexus.shared.contracts.foundation` should work when Python can import from `src`.
- `tests/shared/contracts/foundation/` contains M1 validator tests.
- Foundation schemas load from `contracts/foundation/schemas/`.
- Valid `ChunkRecord` validates.
- Missing `acl_tags` fails validation.
- Unknown top-level fields fail validation.
- Invalid JSONL reports a line number.
- `ContentHasher.hash_text` returns deterministic SHA-256 UTF-8 lowercase hex digests.
- `ContentHasher.hash_text` rejects non-string input.
- `TextNormalizationRules.normalize_text` deterministically normalizes line endings, trailing whitespace, and blank lines.
- `ChunkIdGenerator.generate_chunk_id` returns deterministic `chunk:{source_system}:{hex16}` IDs from normalized text supplied by the caller.
- `RelationIdGenerator.generate_relation_id` returns deterministic `rel:{hex16}` IDs from source, type, and target IDs.
- `AclIdGenerator.generate_acl_id` returns deterministic `acl:{document_id}` IDs without hashing the document ID.
- `TombstoneIdGenerator.generate_tombstone_id` returns deterministic `tomb:{hex16}` IDs from entity type, entity ID, reason, and dataset version.
- `DocumentIdGenerator` returns readable deterministic source entity IDs plus Confluence page, Confluence attachment, and Git file convenience IDs.
- `CanonicalDocumentRecordBuilder.build` returns schema-shaped plain dict records and computes `content_hash` from provided already-normalized body text via `normalized_body_text`.
- `ChunkRecordBuilder.build` returns schema-shaped plain dict records, accepts `chunk_id` and `token_count` as inputs, computes `content_hash` from `text`, copies list inputs, and does not normalize or alter `text`.
- `RelationRecordBuilder.build` returns schema-shaped plain dict records, accepts `relation_id` as input, omits optional `evidence` and `confidence` when absent, and validates only lightweight input types/range before schema validation.
- Foundation record builders share `common_constants.SCHEMA_VERSION` as the single source of truth for schema version.
- `ACLRecordBuilder.build` returns schema-shaped plain dict records, accepts `acl_id` as input, preserves caller-provided `acl_tags`, omits optional fields when absent, preserves empty optional lists, copies retained lists, and does not calculate effective permissions.
- M2C is closed with no additional record builders activated.
- M2D entry condition is satisfied by the existing CanonicalDocument, Chunk, Relation, and ACL builders.
- M2D sample records validate individually and satisfy cross-record reference, ACL-tag compatibility, uniqueness, determinism, and mutable-list isolation checks.
- `JsonlRecordWriter` writes caller-provided JSON-compatible mappings as deterministic JSONL without Foundation schema-specific behavior.
- `DatasetVersionGenerator` formats deterministic UTC dataset versions as `vYYYYMMDD-HHMMSS-ffffffZ`.
- `ManifestRecordBuilder` builds schema-shaped plain dict Manifest records from caller-provided metadata.
- `FoundationSchemaValidator` enforces schema-facing `format: date-time` fields for Python mappings and JSONL records.
- `requirements.txt` declares runtime dependencies, but CI/dev/server environments must install them explicitly with `python -m pip install -r requirements.txt`.
- `FullSnapshotStagingWriter` builds validated machine-readable full-snapshot staging directories with all eight JSONL files and `manifest.json`.
- `FullSnapshotStagingWriter` accepts generic `Mapping` records by copying one record at a time into a plain `dict` before validation and writing.
- `FullSnapshotStagingCompleter` validates an existing M3D staging Manifest, enforces full-snapshot producer invariants, writes deterministic `quality_report.md`, and verifies the exact ten-file complete staging set.
- `FullSnapshotPublisher` atomically renames a completed staging directory into its Manifest-derived final path and atomically updates `LATEST.txt` last.
- The committed M4 golden dataset root validates against the active schemas, has counts matching actual JSONL records, and regenerates byte-for-byte through the full M3 pipeline.
- No PAT/token values should be committed.

## Local Verification Notes

Python 3.12 was installed user-local at `C:\Users\SPen\AppData\Local\Programs\Python\Python312`.

Verified:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared/contracts/foundation -q
6 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/shared/contracts/foundation -q
11 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared/contracts/foundation tests/foundation/domain/rules -q
11 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/shared -q
45 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/shared -q
51 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/shared -q
67 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/shared -q
80 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
102 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
102 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/shared -q
86 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
110 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
144 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
173 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
177 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
177 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
212 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
213 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
213 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/contracts tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
221 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/contracts tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
222 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_jsonl_record_writer.py -q
22 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
244 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_jsonl_record_writer.py -q
23 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
245 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules/test_dataset_version_generator.py -q
16 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/foundation/infrastructure/exporters tests/shared -q
126 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records/test_manifest_record_builder.py -q
43 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/foundation/infrastructure/exporters tests/shared -q
295 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared/contracts/foundation tests/foundation/domain/records -q
186 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared tests/foundation/domain/records -q
186 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/foundation/domain/records tests/shared/contracts/foundation -q
225 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
331 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py -q
18 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/foundation/domain/records tests/shared/contracts/foundation -q
227 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
333 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py -q
19 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/foundation/domain/records tests/shared/contracts/foundation -q
228 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
334 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py -q
26 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/shared/contracts/foundation -q
85 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
360 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py -q
40 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/shared/contracts/foundation -q
125 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
400 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/integration/test_golden_full_snapshot_export.py -q
4 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/foundation/integration tests/shared/contracts/foundation -q
129 passed
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
404 passed
```

`git` is available in the current Codex shell. Review patches were validated with `git apply --reverse --check` where requested.

## M5A - Confluence Inventory Core

- M4 remains complete and unchanged.
- M5 is split into M5A core/scope/reporting, M5B deployment-specific adapter
  and basic correctness pagination, and M5C small real inventory smoke run.
- Added frozen non-secret models `ConfluenceIncludeRoot`,
  `ConfluenceExcludeSubtree`, and `ConfluenceSourceConfig`. Config contains
  `source_id`, `space_key`, include roots, excluded subtrees, keyword hints,
  and preferred `page_size` only; the default page size is 50.
- Added frozen normalized `ConfluencePageMetadata` with ordered ancestor IDs
  and titles, deterministic unique sorted labels, and
  `attachment_count: int | None`. `None` remains unknown and is distinct from
  known zero. Ordered ancestor ID/title fields accept only non-string
  `Sequence` inputs, rejecting set/dict as well as scalar `str`/`bytes` before
  tuple conversion. Labels remain unordered-safe because they are sorted and
  deduplicated. Config collection fields reject scalar `str`/`bytes`.
- Added frozen internal `ConfluenceInventoryItem`, which flattens normalized
  metadata plus `source_id`, `scope_status`, and `scope_reason`. The only scope
  statuses are `included` and `excluded_subtree`; no `crawl_eligible` or
  operational crawl state was added.
- Added `ConfluenceInventoryPort.iter_page_metadata(*, space_key,
  root_page_id, page_size)`. It returns normalized metadata and exposes no raw
  API, HTTP, authentication, endpoint, cursor, or pagination-envelope detail.
- Added pure `ConfluenceScopePolicy.decide()`. Exact-page exclusion wins over
  ancestor exclusion; the nearest excluded ancestor is selected by reversing
  structural ancestor order. Stable reasons are `included_root`,
  `included_descendant`, `excluded_page:<id>`, and
  `excluded_ancestor:<id>`. Keyword hints do not participate.
- Added `BuildConfluenceInventory.execute()`. Include roots are traversed by
  page ID, each root must appear in its own result, and wrong-space or
  unrelated pages fail. Identical duplicate metadata is accepted once;
  conflicting metadata for the same page ID raises `ValueError`.
- Inventory output preserves included and excluded pages and is sorted by
  `(space_key, tuple(ancestor_page_ids), page_id)`.
- Added `ConfluenceInventoryReportWriter.write()`. It requires an existing
  output directory and writes exactly `pages_inventory.jsonl` as strict
  deterministic UTF-8 JSONL and `inventory_report.csv` as fixed-column UTF-8
  CSV. CSV scalar strings beginning with `=`, `+`, `-`, or `@` receive a
  leading apostrophe to prevent spreadsheet formula execution; JSONL preserves
  original values. The writer renders before publication, creates closed
  same-directory temporary files, and publishes with atomic same-directory
  hard links so a concurrent creator cannot be overwritten. Rollback compares
  target/temp file identity before deleting an owned published target.
- Accepted independent-review fixes: P1 no-clobber TOCTOU, P2 CSV formula
  injection, P2 scalar-string collection corruption, and P2 unordered
  ancestor collections. Focused regressions cover all four findings.
- Concrete Confluence deployment type, endpoint/version, pagination response
  shape, and sanitized fixtures were deliberately unresolved at the M5A
  boundary and were resolved by M5B-0. M5A added no HTTP, secrets,
  environment loading, connector, pagination implementation, retry, rate
  limiting, checkpoint, raw store, content/attachment download, or M3/M4
  behavior.

M5A production files:
- `src/knowledgenexus/foundation/domain/models/__init__.py`
- `src/knowledgenexus/foundation/domain/models/confluence_source_config.py`
- `src/knowledgenexus/foundation/domain/models/confluence_page_metadata.py`
- `src/knowledgenexus/foundation/domain/models/confluence_inventory_item.py`
- `src/knowledgenexus/foundation/domain/rules/confluence_scope_policy.py`
- `src/knowledgenexus/foundation/ports/__init__.py`
- `src/knowledgenexus/foundation/ports/confluence_inventory_port.py`
- `src/knowledgenexus/foundation/application/__init__.py`
- `src/knowledgenexus/foundation/application/use_cases/__init__.py`
- `src/knowledgenexus/foundation/application/use_cases/build_confluence_inventory.py`
- `src/knowledgenexus/foundation/infrastructure/exporters/confluence_inventory_report_writer.py`

M5A test files:
- `tests/foundation/domain/models/test_confluence_source_config.py`
- `tests/foundation/domain/rules/test_confluence_scope_policy.py`
- `tests/foundation/application/use_cases/test_build_confluence_inventory.py`
- `tests/foundation/infrastructure/exporters/test_confluence_inventory_report_writer.py`
- `tests/foundation/integration/test_confluence_inventory_core.py`

M5A verification:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/models/test_confluence_source_config.py -q
40 passed in 0.29s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/models/test_confluence_source_config.py tests/foundation/domain/rules/test_confluence_scope_policy.py tests/foundation/application/use_cases/test_build_confluence_inventory.py tests/foundation/infrastructure/exporters/test_confluence_inventory_report_writer.py tests/foundation/integration/test_confluence_inventory_core.py -q
66 passed in 1.45s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain tests/foundation/application/use_cases tests/foundation/infrastructure/exporters tests/foundation/integration -q
447 passed in 8.85s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
473 passed in 9.24s

git diff --check
PASS (exit 0; existing LF-to-CRLF working-copy warnings only)

git diff --cached --check
FAIL (exit 2) only for pre-existing trailing whitespace on line 1 of the v7 and
v7.1 decision logs; neither file is part of any M5A patch.

git apply --reverse --check .local_ai/review/m5a-confluence-inventory-core.patch
PASS (exit 0)

git apply --reverse --check .local_ai/review/m5a-{1-domain-scope,2-inventory-use-case,3-inventory-reporting}.patch
PASS for all three split patches (exit 0 each)
```

Differences from the M5A prompt: none in behavior or boundary. The prompt's
preferred model files were kept separate; metadata-model coverage is
consolidated with source-config model tests. Human exclusion reasons are kept
in config but are not appended to stable machine reasons.

Patch delivery: the replacement full/squashed patch supersedes the previous
M5A full patch. An optional three-patch submission series is also available:
domain/scope after M4, inventory port/use case after domain/scope, and reporting
plus integration after the use case.

## M5B-0 - Offline Confluence API Confirmation Probe

- M5A remains complete and its production source is unchanged.
- The first sanitized live packet is stored at
  `.local_ai/evidence/knowledge-nexus-confluence-packet-20260716-103736`.
  It confirms Confluence Data Center, Bearer PAT authentication, the
  `/rest/api` family, `GET /rest/api/content/{page_id}?expand=version`, JSON
  `_links.next` pagination, a root-relative next URL, and integer version plus
  timestamp metadata. The Confluence version remains unconfirmed.
- The first packet observed four inventory response pages of two records and
  stopped safely with `pagination_truncated: true`; no terminal page was
  claimed. Labels and attachment counts remain unavailable without additional
  requests.
- The first live inventory request is not suitable for M5B: this deployment
  ignored `parent` on `/rest/api/content`. Returned pages did not remain below
  the selected root, so that request must not be reused for filtering.
- The supplied `Tool_TRreport` source is now available. Its
  `count_all_pages.py` already uses `GET /rest/api/search` with CQL
  `space="..." and ancestor=... and type=page`; its `tr_wiki_maker.py` confirms
  the Data Center Bearer PAT and root metadata request shapes.
- The second sanitized packet is stored at
  `.local_ai/evidence/knowledge-nexus-confluence-packet-20260716-111725`.
  Its exact five-file set parses cleanly and contains no real host, space key,
  root ID, PAT marker, Bearer material, cookie value, or unexpected artifact.
- The second packet confirms `/rest/api/search` accepts the root-scoped CQL and
  returns search records containing nested `content`, plus integer `start`,
  `limit`, `size`, and `totalSize`. It returned two records with `size == limit`
  but no `/_links/next`, so the inherited `json_next` profile stopped too early
  and must not be used for this search endpoint.
- Official Data Center search documentation confirms `start`, `limit`, and
  `expand` query parameters and nested content expansions. The final diagnostic
  profile therefore uses confirmed `start_limit` response pointers and requests
  only `content.ancestors`, `content.space`, `content.version`, and
  `content.metadata.labels`; page body and attachments remain excluded.
- The final sanitized packet is stored at
  `.local_ai/evidence/knowledge-nexus-confluence-packet-20260716-124055`.
  It observed four complete CQL response windows (`start` 0, 2, 4, 6; limit 2),
  reached the real `start + size >= total` terminal condition, and reports
  `pagination_truncated: false`. Eight descendants exactly match the selected
  test tree (seven direct children plus one nested descendant).
- The final packet confirms nested search content supplies page ID, title,
  current/page type, space key, ordered ancestor IDs and titles, version number,
  version timestamp, and labels. Attachment count remains deliberately
  unavailable and maps to `None` at the M5 boundary.
- Every sampled descendant contains the selected root in its ordered ancestor
  list. Direct children end with the selected root; the nested descendant ends
  with its direct parent after the root. Ancestors above the selected root are
  also returned, so the adapter must trim both ancestor arrays to the selected
  root before deriving the relative parent and structural path.
- CQL `ancestor` returns descendants but not the selected root itself. The
  adapter must normalize and yield the separately fetched root metadata, then
  yield the paginated descendants. This also satisfies the M5A fail-closed
  requirement that every requested root be present.
- Added a standalone standard-library-only diagnostic under `.local_ai`; it
  imports no KnowledgeNexus production package and requires an explicit,
  non-secret request profile prepared from known working evidence on the
  Confluence-connected machine.
- The diagnostic sends only HTTPS `GET` requests, refuses redirects and
  cross-origin pagination, has no retry behavior, bounds timeout/page count/
  response size, and never auto-loads `.env`.
- The request-profile validator requires root-scoped templates and rejects
  body, attachment, comment, restriction, ACL/permission, rendered HTML,
  download, and export resources, including percent-encoded spellings.
- Supported explicit pagination evidence is `json_next`, `link_header`,
  `cursor_value`, or `start_limit`. URL/cursor modes follow actual server next
  values; numeric mode advances only from validated response windows.
  Non-pagination scope/path/query changes, loops, mismatched/non-advancing
  windows are rejected. Reaching `max_pages` with more data records truncation
  and never claims a terminal page.
- Follow-up hardening compares immutable decoded query pairs as a multiset, so
  Confluence may reorder them without forcing a selector such as `type` to be
  mutable. Any immutable name, value, or duplicate count change still fails.
- Request-profile validation now rejects `type`, `status`, `parent`,
  `ancestor`, and `limit` as mutable pagination keys, in addition to the
  existing space/root/CQL/filter/expansion restrictions.
- Sanitization is default-deny, preserves JSON structure/scalar types/
  nullability/ancestor order/timestamp shape/typed ID identity, immediately
  scrubs unavoidable body leaves, and replaces hosts, titles, identities,
  labels, dynamic text, query data, and cursors deterministically in memory.
- Packet validation scans the rendered artifacts for the base URL/hostname,
  exact/encoded/Base64 credential material, sensitive headers, and optional
  hidden identity terms. Raw responses, the redaction map, credentials, and the
  request profile are never written to the packet.
- Output publication uses same-directory temporary files plus no-clobber hard
  links, accepts only a new or empty directory, validates the exact conditional
  file set, and never overwrites another writer's file. Partial sanitized output
  after a late publication failure is retained safely and must not be copied.
- Added an explicit connected-machine runbook with profile preparation,
  profile-only validation, offline tests, live placeholders, conditional output
  tree, independent no-network packet verification, sanitization checklist,
  environment cleanup, and exit-code handling.
- Independent review fixes cover encoded prohibited-resource bypasses,
  false-positive leak scans, start/limit response mismatch, quoted Link header
  parsing, safe finite response representations, no-clobber cleanup races,
  credential Base64 forms, permission resource aliases, quoted fake
  `rel=next`, and missing root space metadata. The final frozen snapshot has no
  P0-P2 finding from the primary independent reviewer.
- The follow-up working profile is
  `.local_ai/tools/confluence_request_profile.json`. It uses the existing
  root-scoped CQL shape with immutable `space`, `ancestor`, `type=page`, and
  metadata expansion. `limit` remains fixed and `start` is advanced only by the
  validated numeric pagination rule. The temporary
  `confluence_request_profile_1.json` was deliberately not copied verbatim and
  has been removed.
- No live request was made from the Codex machine. M5B-0 requires no additional
  live probe; its evidence is sufficient to begin the production M5B adapter.

M5B-0 standalone bundle:
- `.local_ai/tools/collect_confluence_inventory_packet.py`
- `.local_ai/tools/confluence_request_profile.json`
- `.local_ai/tools/confluence_request_profile.template.json`
- `.local_ai/tools/RUNBOOK_M5B0_CONFLUENCE_PROBE.md`
- `.local_ai/tests/test_collect_confluence_inventory_packet.py`

M5B-0 verification:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s .local_ai/tests -p "test_collect_confluence_inventory_packet.py" -v
54 passed on the final pre-live frozen snapshot

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
473 passed in 9.63s

The 2026-07-16 follow-up adds regression coverage for reordered immutable query
pairs, immutable selector changes, forbidden mutable selector/page-size keys,
and the CQL ancestor profile. Static discovery finds 58 test methods and both
profile JSON files parse. Python is currently unavailable in this Codex
environment. The connected machine successfully validated and executed the
final profile; an updated 58-test console result was not copied back.
```

No patch, commit, staging action, production dependency, generated packet, or
live-network operation belongs to M5B-0 on this machine.

## M5B-1 - Data Center Response Mapping

- Added the pure `ConfluenceDataCenterPageMetadataMapper` infrastructure
  component and immutable `ParsedConfluenceSearchPage` envelope result.
- Root normalization validates ID, page/current state, version shape, and any
  observed `space.key`. The captured root payload may omit `space`, in which
  case M5B-1 uses the already validated expected space. Root labels are optional
  enrichment and normalize to `()` when absent.
- Root paths are always normalized relative to the configured root:
  `parent_page_id=None` and empty ancestor ID/title tuples, regardless of any
  raw ancestors above it.
- Descendant mapping requires the confirmed nested search shape, matching
  space, current page type/status, integer version, a complete first labels
  window, and exactly one selected root in the ordered ancestor path. Ancestors
  above the selected root are removed, duplicate retained ancestor IDs fail
  closed, and the final retained ancestor becomes the parent.
- Search envelope parsing validates actual integer `start`, `limit`, `size`,
  and `totalSize`, exact request start/limit agreement, result count/window
  consistency, and numeric terminal state. It never reads `/_links.next`.
- Added three minimal sanitized committed JSON fixtures derived from the M5B-0
  packet shape and focused positive/fail-closed/fixture-safety tests.
- The packet sanitizer deliberately replaces `totalSize` and `searchDuration`
  values with negative sentinels, so the raw packet cannot replay the numeric
  envelope parser. The committed fixtures use deliberately synthetic,
  internally consistent pagination values; the terminal rule is supported by
  the recorded request trace and observed four-window request sequence.
- Fixture safety uses an allowlist of synthetic keys/scalars plus generic secret
  markers. It does not embed the real host, space key, page IDs, or PAT prefix.
- M5B-1 remains pure/offline: no HTTP, credentials, environment access, CQL
  construction, pagination loop, retry, page body, attachment, or production
  port adapter behavior was added.
- Operational limitation: CQL search is index-backed, so a newly created or
  updated page may appear after a short delay. This is not an M5B-1 blocker and
  no sleep/retry policy belongs in this parser.

M5B-1 verification:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/confluence/test_confluence_data_center_page_metadata_mapper.py -q
44 passed in 1.42s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/models/test_confluence_source_config.py tests/foundation/domain/rules/test_confluence_scope_policy.py tests/foundation/application/use_cases/test_build_confluence_inventory.py tests/foundation/infrastructure/exporters/test_confluence_inventory_report_writer.py tests/foundation/integration/test_confluence_inventory_core.py tests/foundation/infrastructure/confluence/test_confluence_data_center_page_metadata_mapper.py -q
110 passed in 3.60s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared --ignore=tests/foundation/infrastructure/confluence/test_confluence_data_center_inventory_adapter.py -q
517 passed in 18.72s
```

## M5B-2 - Data Center HTTP Adapter and Pagination

- Added a standard-library `urllib` JSON transport with HTTPS-only base URL
  validation, Bearer PAT injection, explicit timeout and response-size limits,
  redirect refusal, JSON content checks, and body/credential-safe errors.
- The transport preserves an optional deployment context path while the adapter
  owns the Data Center `/rest/api` paths and request semantics.
- Added the concrete inventory adapter with lazy network execution, eager input
  validation, one separately fetched root, root-first output, and descendant
  enumeration through root-scoped CQL.
- The root request uses `expand=space,version`. Before mapping or yielding the
  root, the adapter requires `space.key` to be present and exactly match the
  configured space. This request expansion was not observed in M5B-0 and must
  be confirmed by the M5C live smoke run.
- Descendant pagination advances only from validated numeric `start + size`,
  ignores `_links.next`, permits `totalSize` to change between windows, and
  fails closed at an explicit caller-provided `max_search_pages` budget.
- Root labels remain optional and normalize to `()`; M5B-2 deliberately does
  not add a second root request only to enrich labels.
- Retry, rate-limit, checkpoint, resume, page-body, attachment, and permission
  behavior remain outside M5B-2. M7 owns crawl reliability.
- All M5B-2 tests use fake HTTP objects. No live request was made from the Codex
  machine and no credential or deployment identifier was added to the patch.

M5B-2 verification:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/confluence/test_confluence_http_transport.py tests/foundation/infrastructure/confluence/test_confluence_data_center_inventory_adapter.py -q
81 passed in 2.81s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
598 passed in 17.76s
```

## M5C-1 - Offline Live-Inventory Smoke Harness

- M5B-2 is complete and independently approved at commit `a2fe824`. Its
  production source is unchanged by M5C-1.
- Added a committed `foundation/cli/` entrypoint that composes the approved
  transport, adapter, use case, and report writer and duplicates no HTTP, CQL,
  pagination, parsing, normalization, scope, or report-serialization behavior.
- Placement decision: the runner lives in `foundation/cli/`, not
  `presentation/cli/`. It is a composition root that constructs the concrete
  transport, adapter, and report writer, so hosting it under `presentation`
  would introduce a `presentation -> foundation.infrastructure` edge that D34
  does not allow (`presentation -> application use cases` only). D35 names
  `foundation/cli/` for crawl/export jobs and gives `presentation/` only an
  `api/` subtree. v7.5 treats folder layout as a destination but the dependency
  direction as binding from the first file. Under `foundation/cli/` the runner
  imports nothing outside foundation.
- Note: `.local_ai/PROJECT_CONTEXT.md` describes `presentation` as "API/CLI
  entrypoints", which conflicts with D34/D35. v7.5 is the normative contract and
  wins; that steering file is stale and separately owned.
- Runnable as
  `python -m knowledgenexus.foundation.cli.confluence_inventory_smoke`.
- Credentials come only from `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT`. The PAT
  has no CLI flag, is never printed or persisted, and `.env` is never loaded.
- `--output-dir` must be outside the repository working tree, exist, be a
  directory, and be empty. Repo containment uses `os.path.normcase` so the
  Windows check is case-insensitive.
- On success the output directory holds exactly `pages_inventory.jsonl`,
  `inventory_report.csv` (both written by the M5A writer), and
  `m5c_smoke_summary.json`.
- Verification reopens both published reports from disk rather than trusting the
  writer's returned count. JSONL is parsed per line; CSV is counted with
  `csv.reader` because real titles and paths may contain commas, quotes, or
  newlines.
- The summary is guarded by an allowlist of keys and value types. Source ID,
  space key, root page ID, and excluded page IDs are excluded structurally and
  deliberately not text-matched, because a numeric page ID collides with a
  count, a limit, or a SHA-256 hex substring. PAT and base URL are text-matched.
- Report scanning uses header-shaped patterns (`Authorization: Bearer`,
  `Set-Cookie:`), not bare words, because a real page may be titled
  "Authorization Guide".
- `m5c_smoke_summary.json` is success-only. Failure emits one sanitized JSON
  object to stderr with a stable category and a category-specific exit code, and
  removes only runner-created files.
- Known coupling: `_TRANSPORT_MESSAGE_CATEGORIES` mirrors the transport's
  sanitized message literals because `ConfluenceHttpError` carries no status code
  or typed cause. Replace it if a later reliability task adds typed transport
  failures.
- M5C root-label policy: root labels are not requested. `expand=space,version`
  is unchanged. An empty root labels value means "unknown / not observed", never
  "confirmed no labels"; the summary records `root_labels_requested: false` and
  `root_labels_interpretation: "unknown_not_requested"`, and the runbook forbids
  using root labels to choose exclude-subtree configuration. Descendant labels
  remain based on the confirmed search-response metadata.
- No live Confluence request was made on the Codex machine: zero requests, zero
  response pages, no inventory, and no output packet.

M5C-1 independent review fixes (two P1 and one P2, all reproduced before being
accepted):
- P1 argv echo: `argparse.ArgumentParser.error()` wrote the offending arguments
  to stderr before raising, so a mistyped `--pat <token>` printed the token
  verbatim; `main()` caught `SystemExit` only afterwards. Fixed with
  `_SanitizedArgumentParser`, which overrides `error()` — the funnel for every
  parse failure — to raise `SmokeFailure(configuration)` instead of printing.
  `--help` still works because it prints only argparse's own text, never argv.
- P1 orphaned passed summary: ownership was registered after `write_bytes()`
  returned, so a flush/close failure left a complete `status: passed` summary
  that no cleanup removed, breaking the runbook's "presence proves pass" claim.
  Fixed with `_publish_summary` (final form below).
- P2 leftover writer temporaries: the M5A writer swallows failures when removing
  its own temp files, and the runner checked only its two targets, so a run could
  pass while `.pages_inventory.jsonl.<random>.tmp` held a second copy of real
  metadata. Fixed with `_require_exact_report_tree`, which fails closed unless
  the directory holds exactly the two published reports as regular non-symlink
  files. Those temporaries are writer-owned and are left for the operator, never
  deleted here.

M5C-1 round-2 review fix (one P1 regression introduced by the round-1 fix):
- Registering a pathname in `created_paths` is not acquiring ownership of that
  file. Round 1 registered the report targets before the writer ran, so when a
  concurrent creator won the race the writer correctly refused to clobber and
  this runner's cleanup then deleted that process's file. `os.replace()` also
  silently overwrote a concurrently created summary, and the fixed temp name
  `.m5c_smoke_summary.json.tmp` could collide between two runners.
- Fixed by mirroring the M5A writer: report targets are registered only after the
  writer returns successfully; `_publish_summary` uses
  `tempfile.NamedTemporaryFile(delete=False)` for a unique exclusively created
  temp and publishes with no-clobber `os.link`; `summary_path` is registered only
  after that link succeeds; `_require_exact_output_tree` also runs after
  publication so "exactly three files" is a verified postcondition.
- Ownership rule now in force: a path enters `created_paths` only once this
  runner has actually created it.

M5C-1 round-3 review fix (one P2, in a regression test rather than production):
- `test_summary_publish_failure_leaves_no_temp_behind` patched `smoke.os.link`,
  but `os` is a shared module object, so it also replaced the link the M5A writer
  uses. The run failed at the writer's first link and exited `8/report_write`
  without ever calling `_publish_summary`, making the test vacuous for its stated
  purpose. The `== 8` assertion was the tell and was missed.
- Fixed: refuse only a link whose destination is `m5c_smoke_summary.json`,
  delegate the writer's report links to the real `os.link`, expect
  `9/report_verification`, and assert `_publish_summary` actually ran before
  asserting the output directory is empty. A mutation check confirms the test
  fails when the temp registration is dropped.

M5C-1 files:
- `src/knowledgenexus/foundation/cli/__init__.py`
- `src/knowledgenexus/foundation/cli/confluence_inventory_smoke.py`
- `tests/foundation/cli/test_confluence_inventory_smoke.py`
- `docs/runbooks/M5C_CONFLUENCE_INVENTORY_SMOKE.md`

M5C-1 verification:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/cli -q
40 passed in 2.32s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/confluence tests/foundation/application/use_cases tests/foundation/infrastructure/exporters tests/foundation/integration -q
261 passed in 6.29s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared tests/foundation/cli -q
638 passed in 9.08s

git diff --check / git diff --cached --check
PASS (exit 0)

git apply --reverse --check --cached .local_ai/review/m5c-1-live-inventory-smoke-runner.patch
PASS (exit 0)
```

## M5C-2 - Live Confluence Inventory Smoke

- Operator-run read-only smoke against Confluence Data Center on the connected
  primary machine: PASS. This checkout did not perform the live request.
- Operator-reported inventory results: 9 total items, consisting of 1 root and
  8 descendants; all 9 were included and none were excluded by subtree policy.
- The maximum relative depth was 2. Four search windows were consumed with
  `page_size = 2` and `max_search_pages = 10`.
- The published reports were reopened and verified as 9 JSONL records and 9 CSV
  data rows. Their SHA-256 fingerprints are retained in the sanitized review
  summary without retaining the reports themselves.
- The real reports remained outside the repository. No credential material was
  detected, no live output was added to Git, and the run requested no page body,
  attachment, or ACL data.
- Root labels were not requested and remain unknown. They must not be interpreted
  as confirmed empty or used to select excluded subtrees.
- Sanitized evidence: `.local_ai/review/m5c-2-live-inventory-summary.md`.

## M6-0 - Confluence Page Fetch Live Evidence

- Operator-run live probe on the connected primary machine, approved. This
  checkout did not perform the live run and stores no raw production artifact;
  that exclusion is a deliberate sanitization requirement, not missing
  validation. Registered as documentation only.
- Confirmed request shapes (operator observation, not inferred here):
  - page: `GET /rest/api/content/{page_id}?expand=body.storage,space,version,ancestors,metadata.labels`
  - view restriction: `GET /rest/api/content/{page_id}/restriction/byOperation/view`
  - attachments: `GET /rest/api/content/{page_id}/child/attachment?start={offset}&limit={page_size}`
- Confirmed outcomes: page request returned 200; all observed methods were GET;
  response JSON parse passed; `body.storage` contained XHTML; XHTML initial parse
  and serialize/reparse passed; attachment pagination collected 8 windows and 8
  attachments and terminated by the observed `_links.next`; the selected-page
  view restriction returned 404 (classified unavailable); 11 ancestor restriction
  observations returned 404 (classified unavailable); unavailable restriction
  evidence was not read as unrestricted; the downstream ACL consequence stays
  deny-safe as `restricted:unresolved`; the leak scan passed; no credentials
  appeared in the sanitized evidence.
- M6A scope from this evidence: M6A consumes only the page request and preserves
  its exact raw bytes. The restriction and attachment shapes are registered for
  later M6 stages; M6A does not call the restriction or attachment endpoints and
  does not interpret restrictions, ACL, attachments, or XHTML.
- M6A endpoint and `expand` shape are confirmed by approved M6-0, so M6A tests may
  use synthetic/sanitized page-body fixtures without labeling the endpoint shape
  itself as inferred.
- No M6A implementation code changed in the M6-0 state-sync commit.

Review artifact:
- `.local_ai/review/m6-0-confluence-page-fetch-evidence-summary.md`

## M6A - Fetch and Preserve One Raw Page

- Implemented as a review stack over `BASE_COMMIT` `0948252`:
  - `cffa3f1` `[M6A-A]` raw-byte transport capability (`get_bytes`) + tests
  - `de389ec` `[M6A-B]` deterministic atomic raw page store + tests
  - `9ce4590` `[M6A-C]` page adapter + use case + operator entrypoint + tests
  - `a8623d4` `[M6A-D]` end-to-end offline regression test
  - `5542311` `[M6A-E]` Codex review fix: fetch/store behind foundation ports
    (`ConfluencePageFetchPort`, `RawPageStorePort`, `RawPageArtifact` in domain),
    a `tests/architecture` import-boundary guard, and the `response_size_limit`
    category (oversize now exits 9, not `http`)
- Public behaviour: one `GET /rest/api/content/{page_id}?expand=body.storage,space,version,ancestors,metadata.labels`,
  verify (valid JSON, top-level object, `str(id) == requested id`), preserve the
  exact response bytes at `<raw_root>/confluence/pages/<page_id>.json`
  (default `raw_root` = `data/raw`, gitignored), `raw_sha256 = sha256(exact_bytes)`,
  atomic same-directory replacement.
- `get_bytes` was added additively via a shared guarded primitive; `get_json`
  behaviour is unchanged (regression tested). The numeric page-id rule is a new
  shared domain rule; the approved inventory adapter is untouched.
- The 8 MB `max_response_bytes` guard stays enforced and injectable
  (`--max-response-bytes`); it is never auto-raised and a page over the limit
  fails closed with no artifact.
- Out of scope and not done: restriction/attachment/inventory/descendant calls,
  ACL interpretation, XHTML/`body.storage` normalization, `CanonicalDocument`,
  chunking, relations, sync/tombstone, export, embedding/retrieval/chat. M6B was
  not started.
- Status: offline implementation approved by Codex through source `REVIEW_HEAD`
  `5542311`; controlled live PASS on the independent target repository at
  production head `e2823f9ca492becb17d6b2352aeada6bdf85d3ae`. Exit code was 0;
  all seven success checks, artifact existence, temporary cleanup, leak scan,
  and clean-worktree checks passed. The repository owner accepted the
  documentation/state closeout; `M6A_FINAL_HEAD` is the closeout commit containing
  this state. No live run was performed from the Codex machine and no raw
  artifact exists in this repository.

Review artifact:
- `.local_ai/review/m6a-raw-page-fetch-summary.md`
- `.local_ai/review/m6a-live-evidence-summary.md`

The approved command shape was executed on the Confluence-connected primary
machine with credentials in the environment only. The exact local raw-root
location is intentionally not registered. The raw artifact remains outside Git
for M6B input.

```powershell
$env:CONFLUENCE_BASE_URL = "<https-base-url>"
$env:CONFLUENCE_PAT      = "<personal-access-token>"
cd "<repository-root>"
$env:PYTHONPATH = "src"
python -m knowledgenexus.foundation.cli.fetch_raw_confluence_page `
  --page-id "<numeric-page-id>" --raw-root data/raw
```

## M6B - Page-Adjacent Confluence Observations

- Status: complete and approved. Offline implementation and focused detached
  re-review passed at local reviewed source head `fc06d15`. The controlled live
  run passed at independent target production head
  `6ac6a622ddde74bb9756daea040e82ff1df3e48a`. Base commit: `6b23ed3`;
  original round-1 head: `8b4986c`.
- Reads the deterministic M6A artifact through `RawPageReadPort`, validates its
  identity and ordered ancestor IDs before any network call, and never refetches
  the page body.
- Fetches `view` restrictions for ancestors in source order followed by the
  selected page. Exact bodies for 200/401/403/404 are atomically preserved;
  401/403/404 and malformed/unrecognized 200 shapes normalize to `unavailable`,
  never `unrestricted`.
- Fetches attachment metadata from `start=0` and follows only validated,
  root-relative `_links.next` windows for the same page and endpoint. Missing
  `next` alone terminates. Cycles, repeated windows, unsafe links, page-budget
  exhaustion, malformed windows, and duplicate attachment IDs fail closed.
- Raw path rules:
  - restrictions: `<raw_root>/confluence/restrictions/view/<selected_page_id>/<target_page_id>.body`
  - attachment metadata: `<raw_root>/confluence/attachments/metadata/<selected_page_id>/start-<start>_limit-<limit>.json`
- Added one additive status-aware transport method. Existing `get_json` and
  M6A `get_bytes` behavior remain regression-tested.
- Internal normalized observations are plain JSON-compatible dictionaries.
  M6B does not build ACLRecord/MediaAsset, compute effective ACL, parse XHTML,
  download attachment bodies, chunk content, or start M6C.
- No live request was made during implementation or review on the Codex
  machine. The connected primary machine completed the controlled live run
  with exit code 0: it loaded the preserved M6A raw page without refetching the
  body, collected all 12 restriction targets (11 ancestors plus the selected
  page) as unavailable without treating them as unrestricted, and followed 8
  observed attachment windows containing 8 metadata rows without downloading
  attachment bodies. Raw preservation, hash verification, temporary cleanup,
  and leak-scan gates passed.
- The operator worktree contained pre-existing changes before the live run.
  Its before/after baseline was identical, so the run caused no working-tree
  modification; the evidence does not falsely claim that the worktree itself
  was clean.
- Detached review round 1 verdict: changes required. Focused detached re-review
  round 2 approved these accepted fixes:
  - attachment identity now uses a dedicated attachment-ID rule that preserves
    either documented Data Center REST representation (`123` or `att123`)
    without widening the numeric page-ID rule;
  - an I/O failure while draining an `HTTPError` body is translated to the
    sanitized `ConfluenceHttpError` taxonomy, while response-too-large remains
    distinct;
  - a production-store integration test proves the M6A raw-page write path is
    exactly the path consumed by the M6B reader.
- The review's remaining P3 observations are recorded without behavior changes:
  latest-response replacement remains deliberate, CLI interruption behavior is
  unchanged, and internal type assertions remain defensive documentation.

Review artifact:
- `.local_ai/review/m6b-page-observations-implementation-summary.md`
- `.local_ai/review/m6b-live-evidence-summary.md`

## M6C - One-Page Confluence Normalization

- Status: complete and approved. Detached review round 1 requested changes;
  focused re-review approved `[M6C-E]` production code head `2202061` with no
  remaining P0-P2 finding. The offline local real-artifact run then passed.
  `M6C_BASE_COMMIT`: `97a6747`; `M6C_FINAL_HEAD` is the documentation/state
  closeout commit containing this status.
- Reads exactly one deterministic M6A page through `RawPageReadPort`; performs
  no network request and does not refetch the page.
- Validates UTF-8 JSON, object shape, numeric page identity, page type, trusted
  title/space/version fields, and the `body.storage` representation before
  normalization.
- Parses storage XHTML with a deterministic namespace wrapper and the standard
  library XML parser. DOCTYPE/entity declarations, unknown entities, and
  malformed XML fail closed without raw-source disclosure.
- Produces deterministic Markdown/text with NFC, LF endings, stripped trailing
  whitespace, collapsed blank runs, stable source order, and no prepended page
  title.
- Implements the M6C baseline element, simple-table, macro, media-placeholder,
  warning, and counter policies. Complex tables preserve cell text through a
  deterministic fallback and warning. Unsupported elements preserve descendant
  text where safe.
- Review fixes retain observed media filenames, diagram names, and included-page
  title/ID values in the contract-mandated placeholders; preserve unknown
  `plain-text-body` content; and keep fenced code multiline inside lists and
  complex-table fallback output.
- Builds the schema-shaped record with the existing
  `CanonicalDocumentRecordBuilder`, `DocumentIdGenerator`, `AclIdGenerator`, and
  `ContentHasher`. `crawled_at` is an explicit caller value; no wall clock or
  file mtime is read.
- The offline CLI validates the record with `FoundationSchemaValidator`, emits
  counts and fixed status fields only, and persists no normalized output.
- Focused M6C plus architecture verification: 101 passed. Broad Foundation,
  Shared, and architecture verification: 906 passed.
- Detached re-review independently passed 96 focused tests, 884 Foundation
  tests, 17 Shared tests, and 5 architecture tests. It reran the original
  adversarial probes on the reviewed head rather than relying on this summary.
- Local real-artifact acceptance exited 0 with a schema-valid canonical
  document. The preserved raw artifact and complete raw file tree remained
  unchanged, no normalized output file was created, leak scanning passed, and
  no network request was made. The sanitized functional summary reported 3
  handled macros, 9 media placeholders, and zero unhandled macros, dropped TOC,
  unsupported elements, or warnings.
- M6C does not emit ChunkRecord, ACLRecord, MediaAsset, or RelationRecord and
  does not implement export, attachment-body processing, or M6D.

Review artifact:
- `.local_ai/review/m6c-one-page-normalization-implementation-summary.md`
- `.local_ai/review/m6c-local-real-artifact-summary.md`

## M6D Progress

- M6D-A is complete and independently approved at `7642e5c`: BGE-M3 contract,
  immutable profile, strict profile loader, external tokenizer-asset identity,
  and shared text-normalization rules are synchronized.
- M6D-B is complete and independently approved at `740ede5`: the exact pinned
  BGE-M3 fast tokenizer is loaded from explicit verified local bytes and exposes
  sanitized character spans without cache, network, truncation, padding,
  embedding, or chunking behavior.
- M6D-C is implemented at `72e4826`: normalized M6C Markdown is parsed into
  ordered heading sections and prose/table/code blocks without I/O, tokenization,
  budgeting, overlap, or `ChunkRecord` production.
- Independent review reproduced one P2 in the public immutability contract:
  caller-owned lists were retained by frozen dataclasses and remained mutable.
  The candidate fix defensively copies ordered sequences to tuples and rejects
  scalar/unordered/wrong-entry inputs. Verification after the fix: 93 focused
  tests and 1,072 Foundation/Shared/Architecture/Indexing tests passed offline.
- Claude independently re-reviewed the candidate fix, confirmed both patch
  checksums and exact working-tree equivalence, reran 93 focused and 1,072 broad
  offline tests, and approved M6D-C with no remaining P0-P3 finding.
- M6D-C is complete and approved at final head `9b4fec0`.
- M6D-D is complete and independently approved at reviewed code head `bacc22a`.
  It adds the
  deterministic config-driven Confluence wiki chunking use case, exact
  prose/table/code splitting and overlap rules, schema-valid default-deny
  `ChunkRecord` production, deterministic metrics, and an aggregate-only
  offline one-page acceptance CLI.
- Verification uses the exact pinned external BGE-M3 tokenizer bundle with
  offline environment flags and no asset-backed skips. The focused fake and
  real-tokenizer coverage is green, and the full Foundation, Shared,
  Architecture, and Indexing embedding matrix passes: 1,122 tests.
- M6D-D performs no network request or output publication and contains no M6E
  relation extraction, ACL resolution, media processing, embedding, or export.

## M6E Progress

- Status: complete and independently approved. Base: `e336261`; production
  review head: `68a4b08`.
- Adds a strict Jira relation profile and loader, regex-only extraction from the
  M6C normalized body, deterministic page-level `mentions_jira_key` records,
  and canonical/chunk linkage without mutating inputs.
- Entry validation binds the normalized body to the canonical content hash and
  validates canonical/chunk identity, version, provenance, hash, uniqueness,
  and count coherence before relation extraction.
- Extraction uses the locked standalone-token grammar, preserves first-source
  order, deduplicates deterministically, and links only configured project keys.
  Zero relations remains a valid result.
- The result is frozen, `repr=False`, and recursively ownership-isolated. It
  deliberately does not claim deep immutability for nested JSON values.
- The aggregate-only acceptance CLI performs no network request and creates no
  output file. M6E adds no Jira API/PAT, ACL resolution, media/page-link
  relation, embedding, or export behavior.
- Independent detached review found no P0-P2. It reproduced 67 focused tests
  and the complete 1,190-test Foundation/Shared/Architecture/Indexing matrix
  with the exact pinned external BGE-M3 tokenizer bundle and no asset-backed
  skip.

Review artifact:
- `.local_ai/review/m6e-working-tree-review-summary.md`

## M6F Progress

- M6F-A1 is complete on `main` at `2f2325a`: the deny-safe ACL materialization
  contract is active for Foundation M6F and splits the work into focused stages.
  M6F-A locks the trusted M6E result boundary, trusted M6B restriction
  observation boundary, principal projection rules, M6F-B ACL policy, quality
  vocabulary, and future M6F-C capture/acceptance boundaries.
- M6F-A2 is complete on `main` at `2a784b2`: pure ACL principal models and
  projection rules exist for M6F-B. It canonicalizes supported user/group
  principals into deny-safe ACL tags without computing the effective ACL.
- M6F-A3 is complete on `main` at `97c7d7e`: M6E ACL-stage provenance is
  validated before ACL materialization can consume the relation result.
- M6F-A4 is complete on `main` at `0df1818`: M6B restriction observations are
  validated as the normalized source of truth for later ACL materialization.
- M6F-A is complete and approved. It remains a boundary and validation stage
  only; the later M6F-B stage owns materialization.
- M6F-B is complete and approved at production merge head
  `c05f36d7009fd3aac2466eb08ea2be8b0af014f4` (`c05f36d`). The contained
  implementation commit is `cd764f32fbda3bd8338815c08268d13a13a807ae`
  (`cd764f3`).
- The focused M6F-A+B closeout suite passed 248 tests across nine focused test
  files. Independent review has no open P0, P1, or P2 finding.
- M6F-B is fully offline. It required no live Confluence execution and performs
  no network request. Live/full-page acceptance belongs to the later M6F-C1
  capture and M6F-C2 offline composition-acceptance stages.
- Code-only patch sets are transfer artifacts. They are not additional
  production commits and do not define an alternative approved history.
- M6F-D documentation-only closeout is complete. M6F is complete and approved
  with no unresolved P0, P1, or P2 finding.
- M6G-A is complete and independently approved at source-review head
  `dbe5c2f`. It activates the focused one-page export contract over the
  approved M3 and M6F boundaries. No M6G production code existed at that head,
  and M6 overall remains incomplete until the approved one-page snapshot is
  exported through M3.
- The owner accepted and froze the documentation-only M6F-D closeout source
  head at `03c206f`. This closes the M6F-D documentation gate without claiming
  a separate production-code review; M6G-A still requires its own reviewed
  focused contract before any M6G production implementation.
- The owner-approval registration commit is working-repository head `56e7750`;
  it is `SOURCE_REVIEW_BASE` provenance for M6G-A, not a checkout requirement
  for the independent main-machine repository.
- Independent review found no P0, P1, or P2. Two P3 items are deferred to the
  appropriate implementation gates: add contract-consistency coverage in
  M6G-B, and require the byte-identical M4 golden snapshot test in M6G-C.
- M6G-B is complete and independently approved at production head
  `5ee5126db07b2b6cf28453d3224ea902b641068a`, split into the approved B1–B4
  commits. It provides the reusable M6A–M6F composition boundary, trusted
  one-page projection, deterministic profile/config derivation, and contract
  consistency coverage. No staging or publication is performed by M6G-B.
- M6G-C is complete and independently approved at production head
  `5f62bdb`. It composes the trusted one-page projection through the existing
  M3 writer, extended completer, publisher, and offline synthetic acceptance.
  The legacy M3 report/golden path remains compatible; no real raw page,
  sidecar, or production export was used.
- M6G-D-O1 sanitized configuration-failure observability is complete and
  independently approved in both working-review and main-machine histories.
- M6G-D-R3 completed exactly one authorized offline exporter invocation at
  the approved main-machine execution gate. The exporter exited zero. The
  initial post-run validator encountered an operator-script-only empty-stderr
  handling defect after publication; recovery validation invoked the exporter
  zero additional times.
- R3 recovery acceptance passed the approved-head, clean-worktree, sanitized
  success payload, exact published file set, `LATEST` pointer, independent
  manifest row-count, no-staging-residue, and leak gates. The production CLI
  success payload also confirmed schema/projection acceptance, determinism,
  and raw-page/sidecar immutability.
- M6G-D and the M6 one-page vertical slice are complete and approved. External
  snapshot/evidence artifacts remain outside Git. M7 planning is unblocked.
- M6F-C1 offline implementation is complete and independently approved at
  source-review head `bf6b79a`, over sidecar foundation commit `855789d`.
  These foreign-source references are provenance only. Independent review
  found no P0, P1, or P2.
- C1 verification passed 56 focused tests with one Windows-expected POSIX
  permission skip. The implementer full offline matrix passed 1,487 tests with
  the exact pinned BGE-M3 bundle and one skip; the independent reviewer
  reproduced 1,436 non-asset offline tests with one skip.
- Exactly one separately authorized controlled live read-only C1 capture
  completed successfully in the independent execution repository. Exit code
  was zero, the approved seven-line stdout contract passed, stderr was empty,
  and the bounded sidecar envelope gates passed.
- The real sidecar remains external, uncommitted, and unmodified. Its path,
  name, content, exact size, identifiers, principals, and hashes are not
  registered in this repository.
- The execution repository contained one pre-existing tracked
  documentation-only contract deviation. Independent inspection classified it
  P3/non-blocking with no semantic impact on capture, serialization,
  publication, evidence acceptance, or C2 behavior. The live run changed no
  tracked file, no recapture is required, and no P0, P1, or P2 remains.
- C1 live capture must use an external filesystem supporting atomic hard links
  (NTFS or a suitable POSIX filesystem). Unsupported filesystems fail closed as
  `sidecar_publication`; Windows directory fsync is intentionally unsupported
  and best-effort publication therefore performs no directory fsync there.
- Three non-blocking P3 observations are recorded in
  `.local_ai/review/m6f-c1-working-tree-review-summary.md`. The filesystem and
  fsync documentation points are recorded above; the defensive non-bytes
  publication category is explicitly accepted.
- Source-review SHAs in this repository are provenance only for an independent
  patch-transfer repository. Future operator gates must bind to that
  repository's local transfer/execution commit and separately prove production
  tree equivalence to the approved patch set.
- M6F-C2 implementation is complete and independently approved at source-review
  head `74fdbf1c34560b3063fe416d9c746c8b73c0424f` (`74fdbf1`) and source
  production merge head `c12dcc2b685c846f23a013c1b7b4c7950025f2a1`
  (`c12dcc2`). Focused verification passed 105 tests with two
  platform-inapplicable skips; the full offline Foundation/Shared/Architecture/
  embedding matrix passed 1,555 tests with the exact pinned BGE-M3 bundle and
  the same two platform-inapplicable skips. Independent review found no open
  P0, P1, or P2; one non-blocking P3 test-quality note remains.
- The two M6F-C2 code-only patch files are transfer artifacts grouped by strict
  sidecar consumption and offline composition acceptance. They reproduce the
  approved source tree exactly and are not alternative production commits.
- M6F-C2 real captured-sidecar offline acceptance passed at main-machine
  execution head `2034ea4`, transferred from main-machine head `7feae06`.
  Operator transcript evidence proves that the execution head was committed,
  the tracked worktree was clean before the run, and the run left it unchanged.
- All nine scoped production, contract, and test blobs at the main-machine
  execution head exactly match approved source-review head `74fdbf1`.
- The acceptance passed exact ancestry binding, ACL/chunk schema validation,
  ACL-only chunk mutation, ACL propagation, deterministic repeat, raw/sidecar
  immutability, tokenizer integrity, no-network, no-output, and leak-scan gates.
  The independent provenance review approved the evidence and requires no
  rerun. Aggregate evidence is registered in
  `.local_ai/review/m6f-c2-real-offline-acceptance-summary.md`.

## M7-A1/A2/A3 Crawl-Reliability Contract State

- M7-A1 is owner-approved. Its independent review was explicitly waived by
  the owner because the designated reviewer was unavailable; that waiver does
  not extend to M7-A2, M7-A3, or production work.
- M7-A2 materializes the owner-locked
  `m7-crawl-reliability-v1` profile and defines the complete failure taxonomy,
  exact retryable HTTP/transport allowlists, attempt accounting, deterministic
  exponential backoff, Retry-After handling, rate-limit interaction, bounded
  delay/request budgets, interruption behavior, sanitized observability, and
  future acceptance matrix.
- M7-A2 is contract-only. No transport, retry executor, rate limiter,
  checkpoint store, raw-generation store, network request, or production
  behavior was added.
- M7-A3a defines checkpoint/resume, transaction, occurrence, overlapping-root,
  and canonical-path rules in `CHECKPOINT_RESUME_SPEC.md`.
- M7-A3b defines immutable raw generations, the versioned restriction
  status-and-body envelope, no-clobber publication, orphan recovery, retention
  pins, writer locks, and raw budgets in `RAW_GENERATION_SPEC.md`.
- M7-A3c defines canonical fingerprints, controlled-stop behavior, and
  offline/scale/fault/live acceptance gates in `CRAWL_ACCEPTANCE_SPEC.md`.
- The owner approved M7-A2 and M7-A3a/A3b/A3c and accepted the aggregate
  M7 contract gate.
- `M7-CONTRACT-GATE` is approved as the contract baseline. The M7-C production
  stages were authorized and reviewed separately; their durable implementation
  and review/gate outcomes are recorded in the milestone ledger below.

## M7-B1 Structured HTTP Outcome State

- M7-B1 is complete and independently approved.
- The Confluence transport now emits strict, body-free structured metadata for
  HTTP status, redirects, typed transport failures, Retry-After observations,
  payload failures, invalid status, and response-size failures.
- Existing M5B/M6B behavior is preserved: status-aware restriction responses
  retain exact status/body, redirects remain terminal, and caller input
  validation still fails before outbound I/O.
- M7-B1 adds no retry decision, retry loop, sleep, rate limiter, profile
  loading, request-budget accounting, checkpoint, raw-generation, fingerprint,
  controlled-stop, live request, or credential behavior.
- Focused B1/M5B/M6B verification passed 217 tests. The broader offline
  non-asset Foundation/Shared/Architecture matrix passed 1,821 tests with two
  platform-inapplicable skips.
- Independent adversarial review fixed and verified two P2 findings:
  interpreter-limit Retry-After decimals now become a sanitized ignored
  observation, and `ConfluenceHttpError.metadata` is read-only by interface.
- No open P0, P1, or P2 remains.

## M7-B2 Pure Bounded Retry-Policy State

- M7-B2 is complete and independently approved.
- The approved `m7-crawl-reliability-v1` mapping is bound exactly, including
  all 23 fields and decoded types; changing any value requires a new reviewed
  profile version.
- Pure domain evaluators classify B1 HTTP/transport/payload facts, preserve
  Confluence restriction semantic statuses, perform request-budget preflight,
  and apply the approved attempt, request, Retry-After, single-delay, and
  accumulated-delay precedence.
- Decisions are immutable, value-comparable, value-hiding, and constrained by
  exact outcome/stable-kind combinations.
- M7-B2 performs no HTTP call, clock read, sleep, pacing calculation, counter
  mutation, filesystem/YAML loading, logging, checkpointing, raw publication,
  or live execution.
- Focused B2/B1 verification passed 416 tests. The broader offline non-asset
  Foundation/Shared/Architecture matrix passed 2,072 tests with two
  platform-inapplicable skips.
- Independent adversarial review fixed the duplicate pytest-module name,
  overflow from extremely large Retry-After/rate-limit values, and exact-int
  request-budget validation. No open P0, P1, or P2 remains.

## M7-B3 Retrying and Rate-Limited Executor State

- M7-B3 is complete and independently approved with no open P0, P1, or P2.
- B1 retains ownership of request construction, urllib execution, redirects,
  content-type checks, structured HTTP failures, and bounded response bodies.
- B3 owns only request-budget enforcement, injected monotonic pacing, the
  bounded attempt loop, one selected retry sleep, and run/request counters.
- Caller input and the complete urllib request are prepared before any clock
  read, sleep, counter mutation, or outbound-start callback. Unsafe control,
  traversal, and unencodable inputs fail closed with zero attempts.
- The status-aware seam preserves the final exact response together with its
  terminal policy decision; M6B-compatible callers retain the existing
  response-only projection.
- Final independent verification passed 379 focused B1/B2/B3 tests and 615
  broader Confluence/retry/M6B/architecture tests. One non-blocking P3 remains:
  the public result model does not validate the exact stable-kind pairing for
  manually constructed redirect/non-retryable responses; executor-produced
  values are correct.
- M7-B3 added no checkpoint, raw-generation, fingerprint, controlled-stop,
  credential/configuration, or live-network behavior.

## M7-C Durable Milestone Ledger

The entries below are the portable milestone state. Review and gate outcomes
are recorded without using repository-local commit SHAs as status.

| Milestone | Status | Review / gate outcome |
|---|---|---|
| M7-C0 trusted crawl fingerprint | complete | Independent review `PASS`; trusted canonical fingerprint gate closed. |
| M7-C1-A normalized inventory window seam | complete | Independent review `PASS`; normalized single-window compatibility gate closed. |
| M7-C1-B run/occurrence domain | complete | Technical and governance reviews `PASS`; pure domain boundary gate closed. |
| M7-C2-A checkpoint schema | complete | Schema correction included; technical and governance reviews `PASS`; exact-v1/no-migration gate closed. |
| M7-C2-B run/session registry | complete | Integrated C4/C5 acceptance `PASS`; no separate standalone review is claimed; start/resume/session lifecycle gate is closed. |
| M7-C2-C atomic inventory checkpoint session | complete | Integrated C4/C5 acceptance `PASS`; no separate standalone review is claimed; atomic root/window transaction and replay gate is closed. |
| M7-C2-D durable inventory readback | complete | Integrated C5 acceptance `PASS`; no separate standalone review is claimed; canonical ordering/readback gate is closed. |
| M7-C3-A locked workspace dependency | complete | Independent review `PASS`; integrated checkpoint acceptance `PASS`; lock-before-open, path-safety, and capability-lifetime gates are closed. |
| M7-C3-B outbound reservation | complete | Independent review `PASS`; durable reservation denial-before-request gate passes. |
| M7-C4-A durable inventory orchestration | complete | Independent review `PASS`; coordinator/lock/retry/checkpoint integration gate passes. |
| M7-C4-B controlled checkpoint stop | complete | Integrated C5 pause/resume acceptance `PASS`; no separate standalone review is claimed; controlled-stop gate is closed. |
| M7-C5 current state | bounded durability stages complete; 100k scale gate deferred | Inventory-only acceptance consolidation independently reviewed `PASS`; 10k correctness baseline `PASS`; C5-B1 independent review `PASS`; C5-B2 measurement package `PASS` only. Owner accepts bounded M7 closure; the 100k scale gate and RSS threshold remain deferred. |

## M7-C5 Acceptance and Scale State

- The inventory-only M7-C5 acceptance consolidation is complete with a fresh
  independent review `PASS`. It composes the approved B1/B2 retry and pacing
  seam with durable reservation, crash/replay, transaction rollback,
  controlled-stop, cap, duplicate, excluded-budget, and exact-ID evidence.
- Sanitized aggregate evidence is recorded in
  `.local_ai/review/m7-c5-acceptance-consolidation-evidence.md`.
- This subsection closes only the durable inventory slice. Raw-generation
  closure is recorded in the M7-D state below; live and 100k scale acceptance
  remain outside this bounded closeout.

## M7-C5 Scale and Performance State

- M7-C5-B1 is complete, pushed, and independently approved. It preserves the
  durability-first validation boundary while adding only bounded local checks
  and cadence-based full validation.
- M7-C5-B2 measurement is complete with `VERDICT: PASS` for the measurement
  package only. The 100,000-page acceptance gate remains incomplete; its
  timeout and working-set observations are evidence, not a scale PASS.
- The owner explicitly deferred 100,000-page performance optimization. Any
  future lock/sidecar, validation-cadence, schema/index, or memory-threshold
  change needs a separate owner-authorized and independently reviewed stage.
- The owner accepts the bounded M7 stages as complete while retaining the
  100,000-page scale gate as a separate deferred follow-up. This is a bounded
  roadmap closeout, not a 100,000-page scale PASS.
- M7-D3 raw-page store is complete and independently reviewed with
  `VERDICT: PASS`. It remains offline-only and does not authorize live crawl
  integration, checkpoint advancement, budgets, locks, attachments, CLI,
  retention, migration, or network behavior.

## M7-D Raw-Generation State

- M7-D1/D2 contract and restriction evidence stages are complete and
  independently reviewed.
- M7-D3 generation-scoped immutable raw-page envelope/store is complete;
  focused and regression tests pass and the independent review verdict is
  `PASS`.
- M7-D beyond D3 is now stage-gated under the owner's full-roadmap
  authorization. D4-A and D4-B are complete and independently reviewed
  `PASS`; both use bounded no-follow readback, preserve immutable artifacts,
  and reject unsafe targets without mutation. D4-B focused validation was
  `34 passed, 3 skipped`; D2/D3/D4-A regression validation was `123 passed,
 3 skipped`, with compileall and diff-check passing.
- M7-D5-A is complete and independently reviewed `PASS`. It adds an exact-v1
  raw-page progress table to fresh checkpoint workspaces only; existing or
  malformed schemas fail closed with no migration. Replay is operation-specific,
  same-lock/same-database, readback-verified, idempotent for identical
  evidence, conflicting for differing evidence, and limited to same-run known
  inventory occurrences. Focused checkpoint/raw/architecture validation was
  `255 passed, 14 skipped`; compileall and diff-check passed. D5-B restriction
  replay is also complete and independently reviewed `PASS`. Its focused
  replay suite passed `15` tests; the combined checkpoint/port/raw-restriction
  regression suite passed `257` tests with `15` skipped. Both replay paths now
  fail closed when the durable session is paused or completed. The 100k scale
  gate remains incomplete and is not implied by this authorization or by M7-D5.

## M8-A Normalization Fidelity and Layout Semantics

- Status: complete and independently reviewed `PASS`.
- The normalizer now treats Confluence `layout`, `layout-section`, and
  `layout-cell` as transparent structural blocks. Source order and canonical
  block boundaries are preserved without changing the existing one-page result
  contract.
- Existing complex-table fallback behavior remains unchanged and is explicitly
  deferred to M8-B. No schema, tokenizer, `chunker_version`, config identity,
  raw-store, network, export, ACL, relation, or media behavior changed.
- Changed production/test files:
  `src/knowledgenexus/foundation/infrastructure/processors/confluence_storage_xhtml_normalizer.py`
  and
  `tests/foundation/infrastructure/processors/test_confluence_storage_xhtml_normalizer.py`.
- Validation: focused normalizer suite `47 passed`; normalize/page-structure
  regression `98 passed` using an explicit workspace pytest basetemp;
  `python -m compileall -q src tests` passed; `git diff --check` passed.
- Independent review artifact:
  `.codex-workflow/20260804-m8a/04-review-1.md`, verdict `PASS`.
- Environment-only gaps: the asset-backed BGE-M3 test was not invoked without
  `--tokenizer-assets-dir`; the first broad run also hit a machine temp-
  directory permission error and passed when rerun with an explicit basetemp.
- Next stage: M8-C macro/placeholder/reference-intent completeness.

## M8-B Complex-Table No-Loss Migration

- Status: complete and independently reviewed `PASS`.
- Objective: replace the lossy M6C complex-table fallback with deterministic
  no-loss grids/fallbacks while preserving simple-table bytes and the active
  BGE-M3/`chunker_version=1.2.0` profile.
- Policy identity: `confluence-table-no-loss-v1`; bounded rows/columns/slots,
  cell/output bytes, and nested-table depth fail closed with sanitized stable
  categories. Span markers are ordered `[rowspan:N]` then `[colspan:N]`;
  invalid grids use the exact row-preserving `[table]` grammar.
- Config migration: one-page export identity is now `one-page-export-v2` and
  canonical config JSON includes the code-owned `normalization_policy_id`.
  Schemas and chunker version remain unchanged. The next production export is
  required to be an explicit `full_snapshot`; no delta bridge is authorized.
- Changed files:
  `src/knowledgenexus/foundation/infrastructure/processors/confluence_storage_xhtml_normalizer.py`,
  `src/knowledgenexus/foundation/domain/models/one_page_export.py`,
  `contracts/foundation/ONE_PAGE_EXPORT_SPEC.md`,
  `tests/foundation/infrastructure/processors/test_confluence_storage_xhtml_normalizer.py`,
  `tests/foundation/domain/models/test_one_page_export.py`, plus sanitized
  stage artifacts under `.codex-workflow/20260804-m8b/`.
- Validation: focused normalizer `60 passed`; parser/chunker/config/export
  regression `258 passed, 1 skipped`; `compileall` passed; scoped `git diff
  --check` passed. The BGE-M3 asset-backed test remains an environment-only
  skip without `--tokenizer-assets-dir`.
- Broad offline Foundation/Shared/Architecture run reached `2526 passed,
  35 skipped, 40 failed`; the failures are machine path-policy/sidecar smoke
  failures plus the historical M6G dirty-file guard that rejects the intended
  M8-B change to `one_page_export.py`. This is not claimed as a broad PASS.
- Plan/review artifacts:
  `.codex-workflow/20260804-m8b/PLAN.input.md`,
  `.codex-workflow/20260804-m8b/01-plan-review.md`,
  `.codex-workflow/20260804-m8b/02-plan-revised.md`,
  `.codex-workflow/20260804-m8b/03-migration.md`,
  `.codex-workflow/20260804-m8b/04-implementation.md`, and
  `.codex-workflow/20260804-m8b/05-review-1.md` (`VERDICT: PASS`).
- Commit/push provenance: commit `2cb9310` (`feat(foundation): complete M8-B
  complex table migration`) pushed to `origin/codex/m8-m9`. The documentation
  backfill is a follow-up closeout commit on the same branch.

## M8-C Macro, Placeholder, and Reference Intents

- Status: complete and independently reviewed `PASS`.
- Objective: preserve the M6C/M8-B normalization contract while adding a
  sanitized internal side stream for drawio, image/attachment, and include-page
  references. The side stream performs no resolution, network access, export,
  relation creation, media extraction, or raw-store mutation.
- Contract: `NormalizationReferenceIntent` is immutable and runtime-validated
  for exact kind/status pairs, bounded NFC one-line identities, one-based
  contiguous source ordinals, and unknown-identity rules. Existing result model
  constructors remain compatible through `reference_intents=()` defaults; mutable
  counters, warnings, and canonical documents are defensively copied.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/confluence_page_content.py`,
  `src/knowledgenexus/foundation/domain/models/__init__.py`,
  `src/knowledgenexus/foundation/infrastructure/processors/confluence_storage_xhtml_normalizer.py`,
  and
  `src/knowledgenexus/foundation/application/use_cases/normalize_confluence_page.py`.
  Focused tests were added under the corresponding model, normalizer, and use-
  case test paths.
- Validation: focused M8-C suite `99 passed`; bounded parser/chunker/CLI/E2E
  regression `87 passed` with an explicit workspace basetemp; architecture
  suite `69 passed`; `python -m compileall -q src tests` passed; scoped
  `git diff --check` passed. The default pytest temp root remains a known
  machine permission issue, so the bounded regression used
  `.pytest-m8c-reg`/`.pytest-m8c-independent-review`.
- Review artifact: `.codex-workflow/20260804-m8c/05-review-1.md`, verdict
  `PASS`; the independent review's initial P1 on non-contiguous ordinals was
  fixed and rechecked with adversarial tests.
- Commit/push provenance: implementation commit `a310a67`
  (`feat(foundation): complete M8-C reference intents`) was pushed to
  `origin/codex/m8-m9`; this SHA is provenance only, not the milestone source
  of truth.
- Residual boundaries: intent consumers, media/relation resolution, generation-
  bound page-set processing, chunk handoff, and all M9 tracks remain pending.

## M8-D Generation-Bound Deterministic Page Sets

- Status: complete and independently reviewed `PASS`.
- Objective: compose the approved normalizer, wiki structure parser, and
  BGE-M3 M6D chunker over an explicit ordered set of preserved M7 raw-page
  envelopes without checkpoint, raw, or export mutation.
- Contract: exact `CrawlRunId` run/generation identity, active profile identity
  `bge-m3:medium:chunker-1.2.0`, non-empty ordered work items, source-version
  equality, HTTP-200 envelope validation, all-or-nothing records, fixed
  cross-checked metrics, recursively JSON-safe defensive copies, and sanitized
  category-only errors.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/confluence_page_set.py`,
  `src/knowledgenexus/foundation/domain/models/__init__.py`,
  `src/knowledgenexus/foundation/application/use_cases/process_confluence_page_set.py`,
  and
  `src/knowledgenexus/foundation/application/use_cases/__init__.py`.
  Synthetic model/use-case tests were added under
  `tests/foundation/domain/models/test_confluence_page_set.py` and
  `tests/foundation/application/use_cases/test_process_confluence_page_set.py`.
- Validation: focused M8-D model/use-case suite `17 passed`; bounded raw-store,
  normalizer, parser, and chunker regression `147 passed`; architecture suite
  `70 passed`; `python -m compileall -q src tests` passed; scoped
  `git diff --check` passed. Explicit workspace basetemp was used because the
  machine default pytest temp root has a known permission failure.
- Review artifact: `.codex-workflow/20260804-m8d/05-review-1.md`, verdict
  `PASS`. The independent re-review covered malformed dependency results,
  profile/asset/type drift, envelope/source-version and canonical page identity,
  nested JSON, metric/error invariants, and leak-safe failure strings.
- Commit/push provenance: implementation commit `85f5054`
  (`feat(foundation): complete M8-D page set processing`) was pushed to
  `origin/codex/m8-m9`; this SHA is provenance only, not the milestone source
  of truth.
- Residual boundaries: M8-E chunk handoff and all M9 tracks remain pending;
  M10 full-snapshot work remains separately gated.
- Post-closeout technical debt (deferred until post-POC product hardening):
  `process_confluence_page_set._profile_identity` currently repeats the active
  `ChunkingProfile` contract as application-level literals. This is strict but
  not single-source-of-truth. Product hardening must centralize profile
  identity/fingerprint derivation and add drift tests; the independent M8-D
  review did not catch this duplication.

## M8-E Chunk Stability and Update-Propagation Handoff

- Status: complete and independently reviewed `PASS`.
- Objective: expose a deterministic, immutable hash/ID/count-only handoff for
  M9-D without carrying normalized page text or changing Foundation schemas.
- Contract: one-document `DocumentChunkSetSummary` plus an ordered M8-D
  page-set adapter; exact Confluence source/profile/chunker identity, schema
  validation before field selection, chunk content-hash recomputation from
  transient text, global final-ID uniqueness, contiguous part metadata,
  cross-document/order/count invariants, defensive ownership, sanitized
  malformed-boundary errors, compact sorted-key UTF-8 JSON, and SHA-256 digest.
  Normalized-body hash recomputation, tokenizer invocation, and private
  chunk-ID preimage reconstruction remain M8-D-owned.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/chunk_stability.py`,
  `src/knowledgenexus/foundation/domain/rules/chunk_stability_builder.py`,
  `src/knowledgenexus/foundation/domain/models/__init__.py`, and
  `src/knowledgenexus/foundation/domain/rules/__init__.py`.
  Focused adversarial tests are in
  `tests/foundation/domain/models/test_chunk_stability.py`.
- Validation: focused M8-E `23 passed`; bounded page-set/chunker/schema
  regression `85 passed`; architecture `16 passed`; compileall and scoped
  diff-check passed. Explicit workspace basetemps were used due the known
  machine pytest temp-root permission issue.
- Review artifact: `.codex-workflow/20260804-m8e/05-review-1.md`, verdict
  `PASS`; follow-up review fixed validator side-effect/error leakage, typed
  page-set bypass, exact string-subclass identity, single-part metadata, and
  cross-document duplicate-ID gaps.
- Residual boundaries: M9-A media, M9-B Git, M9-C symbols, and M9-D
  tombstone/delta propagation remain pending; M10 full-snapshot work remains
  separately gated.

## M8-AC Controlled Mini-Corpus Acceptance (M8-D.5)

- Status: implementation and independent re-review complete `PASS`; real gate
  complete on the operator-supplied bounded corpus.
- Objective: run two fresh deterministic, aggregate-only passes over an
  operator-approved 10-20 page M7 generation before relying on M10 for the
  first real-corpus signal. The seam is retroactive M8-D.5 evidence and does
  not change M8-D/E processing semantics.
- Contract: exact run/generation-bound selection, source-byte and explicit
  write fingerprints, per-pass M8-D/M8-E digests, tokenizer-asset digest,
  chunk/token distributions and coverage observations, strict status/counter
  validation, exact negative probes, sanitized CLI categories, no raw content
  or report leaks, and no output/checkpoint/export writes.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/confluence_mini_corpus_acceptance.py`,
  `src/knowledgenexus/foundation/application/use_cases/accept_confluence_mini_corpus.py`,
  `src/knowledgenexus/foundation/cli/accept_confluence_mini_corpus.py`, plus
  the relevant package exports. Focused adversarial tests cover models,
  use-case, CLI, and architecture boundaries.
- Validation: focused fix suite `15 passed, 2 skipped`; `python -m compileall
  -q src tests` passed; scoped `git diff --check` passed. The bounded M8-D/E
  regression selection reached `164 passed, 1 failed`; the single failure is
  the unrelated pre-existing canonical-document schema test in
  `test_build_confluence_chunks.py`.
- Review artifacts:
  `.codex-workflow/20260805-m8ac/05-review-1.md` (`CHANGES_REQUIRED`),
  `.codex-workflow/20260805-m8ac/08-review-2.md` (`PASS`).
- Real acceptance receipt (2026-08-08, aggregate-only): 10 requested and 10
  succeeded pages; 401 chunks; 20 reference intents across 7 pages; 8 table
  pages; content kinds `code_block=143`, `prose=231`, `table=27`; deterministic
  repeat, source/selection stability, negative probe, and no-write checks all
  passed. The pinned tokenizer asset digest matched the active profile;
  `page_set_digest=27a8b4e8c4ddf3669c6597aaf59bd85045ad0b646b4e9255efad2d795ed6ae9a`,
  `chunk_stability_digest=d6078afa3c096cfce50924a831fe20167ef4617b4e9a515cbd15d91b533d42a1`,
  and the final sanitized receipt digest was
  `2534b13b9e3f86ad97750ae1968f3c15e675a3c857098cfac33d583d24c22ac5`.
  Raw pages and runtime artifacts remain outside Git.

## M9-A1 Metadata-First Media Contract

- Status: complete and independently reviewed `PASS`.
- Objective: define a metadata-first media observation/policy/result seam and
  deterministic relation intents without downloading bodies, parsing files,
  OCR, raw-store writes, export, network, or other I/O.
- Contract: immutable, runtime-validated `MediaAsset` records with exact
  schema/status matrix, NFC and byte-bound checks, deterministic attachment
  ordering, atomic batch mapping, sanitized category-only errors, and explicit
  drawio/image relation-intent semantics. `include_page` remains omitted.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/media_materialization.py`,
  `src/knowledgenexus/foundation/domain/rules/media_asset_record_builder.py`,
  `src/knowledgenexus/foundation/domain/models/__init__.py`, and
  `src/knowledgenexus/foundation/domain/rules/__init__.py`.
  Focused adversarial tests are in
  `tests/foundation/domain/models/test_media_materialization.py`.
- Validation: focused `11 passed`; bounded attachment/schema regression
  `87 passed`; architecture `16 passed`; compileall and scoped diff-check
  passed. The independent review covered malformed runtime types, exact
  status/schema combinations, deterministic ordering, atomicity, and no-I/O
  behavior; verdict `PASS` in
  `.codex-workflow/20260805-m9a/05-review-1.md`.
- M9-A1 closeout is recorded above; its commit/push closeout remains grouped
  with the current approved M9-A2 stage on this branch.

## M9-A2 Attachment Body Fetch and Store Boundary

- Status: complete and independently reviewed `PASS`.
- Objective: fetch one policy-selected attachment body through a typed port,
  validate the bounded response, publish canonical immutable raw evidence, and
  return a downloaded-but-not-processed `MediaAsset` result without parsing,
  OCR, export, checkpoint, ACL, or downstream storage behavior.
- Contract: explicit absolute `data_root`, frozen body/total/free-disk budget,
  category-only sanitized ports/errors, canonical envelope JSON, no-clobber
  replay/conflict semantics, bounded regular-file scan, hardlink/symlink/
  reparse rejection, root/parent identity checks across scan-to-publication,
  canonicalized per-root budget serialization, and fail-closed forged-input and
  unexpected-exception handling.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/media_body_materialization.py`,
  `src/knowledgenexus/foundation/ports/confluence_attachment_body_fetch_port.py`,
  `src/knowledgenexus/foundation/ports/confluence_raw_attachment_store_port.py`,
  `src/knowledgenexus/foundation/application/use_cases/fetch_and_store_confluence_attachment_body.py`,
  `src/knowledgenexus/foundation/infrastructure/raw_store/confluence_raw_attachment_store.py`,
  and the corresponding package exports. Focused adversarial tests cover
  models, use-case, raw store, and architecture boundaries.
- Validation: focused `37 passed, 2 skipped`; M9-A1/raw-store regression
  selection `50 passed, 3 skipped`; `python -m compileall -q src tests` passed;
  scoped `git diff --check` passed.
- Review artifacts:
  `.codex-workflow/20260805-m9a2/05-review-1.md` (`CHANGES_REQUIRED`),
  `.codex-workflow/20260805-m9a2/08-review-2.md` (`PASS`).
- Commit/push closeout is complete on `codex/m8-m9` (`fcd9935`); M9-A3 was
  implemented as the next separately planned and reviewed stage.

## M9-A3 Offline Draw.io/PDF/OCR Processors

- Status: complete and independently reviewed `PASS`.
- Objective: process one already-materialized M9-A2 attachment body offline,
  preserving the schema-shaped MediaAsset evidence while returning an
  in-memory extraction-detail projection for draw.io, digital PDF text, or
  selected-image OCR.
- Contract: stdlib source-first draw.io XML parsing with DTD/entity rejection,
  bounded deterministic labels/edges/containers, closed PDF/OCR capability
  identities, strict page/image counters and output budgets, exact `parsed` /
  `ocr` / `failed` status matrix, MIME/filename dispatch, envelope-bound
  content hash/raw URI, sanitized failures, and no attachment-text chunks or
  side-effecting engine/network/file behavior.
- Changed production files:
  `src/knowledgenexus/foundation/domain/models/drawio_xml.py`,
  `src/knowledgenexus/foundation/domain/models/media_processing.py`,
  `src/knowledgenexus/foundation/ports/media_processing_port.py`,
  `src/knowledgenexus/foundation/infrastructure/processors/drawio_xml_processor.py`,
  `src/knowledgenexus/foundation/infrastructure/processors/media_attachment_processors.py`,
  `src/knowledgenexus/foundation/application/use_cases/process_confluence_media_attachment.py`,
  and package exports.
- Validation: focused M9-A3 suite `30 passed`; architecture suite `80 passed`;
  M9-A1/A2 regression `48 passed, 2 skipped`; M8-D/E bounded regression
  `43 passed`; `python -m compileall -q src tests` and scoped `git diff --check`
  passed. The broad Foundation suite remains environment-blocked by known
  tokenizer-asset/runtime and unrelated CLI/temp-root failures; no M9-A3
  failure was observed in the bounded suites.
- Review artifacts:
  `.codex-workflow/20260805-m9a3/05-review-1.md` records initial findings and
  fixes; `.codex-workflow/20260805-m9a3/08-review-2.md` records the fresh
  independent `VERDICT: PASS`.

## M9-A4 OCR Productionization Stage A

- Status: bounded contract/policy seam complete and independently reviewed
  `PASS`; production engine activation remains `pending_external_input`.
- Added runtime-validated OCR limits/request/result envelopes, canonical
  source/page/image binding, PDF rasterizer capability boundary, digital-first
  mixed-PDF/image-only fallback, selected-image OCR policy, resource/quality/
  cancellation/deadline limits, and fail-closed no-partial-result handling.
  Existing fixture capability identities remain unchanged; no subprocess,
  network, cloud, or engine runtime was introduced.
- Validation: focused Fix3 `30 passed`; M9/media regression `37 passed`;
  compileall and diff-check passed. Fresh independent review is
  `.codex-workflow/20260806-scale-ocr/17-m9a4-fix3-independent-review.md`
  with `VERDICT: PASS`.
- Engine gate: an approval artifact is still required to identify the engine,
  runtime/model/build identity, offline/network policy, limits, and sanitized
  acceptance evidence before any production OCR claim.

## M9-B Pinned Local Git Code-Document Seam

- Status: complete and independently reviewed `PASS`.
- Objective: read source bytes only from the pinned local `spen-sdk` commit on
  `develop`, build schema-valid Git `CanonicalDocument` records, and emit
  deterministic fallback `code_window` chunks while reserving C++/Java symbol
  authority for M9-C.
- Contract: exact repository/branch/commit identity, strict POSIX path and
  casefold policy, generated/vendor/binary exclusions, bounded tree/file/raw/
  normalized/memory budgets, commit-bound blob reads, atomic no-partial-result
  behavior, active BGE-M3 medium profile, and sanitized fail-closed public
  boundaries.
- Validation: focused M9-B `35 passed`; M9-A regression `47 passed`; M8-D/E
  regression `70 passed`; compileall and scoped diff-check passed.
- Review artifact: `.codex-workflow/20260804-m9b/40-review-18.md` records the
  final fresh independent `VERDICT: PASS` after bounded fixes.

## M9-C Minimal Symbol Index

- Status: complete and independently re-reviewed `PASS`.
- Objective: activate the bounded C++/Java tree-sitter symbol stream over
  M9-B authority observations while preserving M9-B's fallback-plan invariants.
- Contract: atomic `BuildGitSymbols` result, exact commit/path provenance,
  runtime-validated parser spans, deterministic class/namespace/package/method/
  function/enum/struct/interface extraction, overload IDs, schema-valid
  `SymbolRecord` and `code_symbol`/error-only `code_window` chunks, pinned
  BGE-M3 token/profile identity, and no export/network/raw/checkpoint side
  effects. Kotlin/XML remain M9-B fallback-only.
- Parser dependencies: `tree-sitter==0.25.2`, `tree-sitter-cpp==0.23.4`,
  `tree-sitter-java==0.23.5`.
- Validation: focused M9-C `10 passed`; M9-B regression `27 passed`; M8-D/E
  regression `40 passed`; M9-A regression `65 passed`; architecture `85 passed`;
  compileall and diff-check passed.
- Review artifacts: `.codex-workflow/20260805-m9c/05-review-1.md` records the
  initial `FAIL` and two P1 findings; bounded fix plan/review are in
  `06-fix-plan.input.md` and `07-fix-plan-review.md`; fresh
  `.codex-workflow/20260805-m9c/09-review-2.md` records final `VERDICT: PASS`.

## M9-D1 Tombstone Contract and Explicit Cascade

- Status: complete and independently reviewed `PASS`.
- Added immutable/runtime-validated `TombstoneTarget`, request, metrics, and
  result models with exact field sets, schema-shaped record validation,
  deterministic ID preimage checks, nullable optional fields, cycle-safe JSON
  validation, and sanitized impossible-counter/forged-input failures.
- Added schema-valid `TombstoneRecordBuilder` with validator mutation guards
  and atomic `ProjectTombstones` document-root cascade with fixed ordering,
  injected validator dependency, canonical bytes, duplicate/collision policy,
  and no filesystem/network/export/checkpoint side effects.
- Validation: focused `31 passed`; M9/M8 regression `42 passed`; architecture/
  schema `37 passed`; full architecture `86 passed`; compileall/diff-check
  passed. Final independent review is `VERDICT: PASS` in
  `.codex-workflow/20260805-m9d1/19-review-final.md`.
- Residual boundary: M8-AC real mini-corpus gate remains
  `pending_external_input`; M9-D2 is recorded in the next section.

## M9-D2 Delta and Inventory Diff Propagation

- Status: complete and independently reviewed `PASS`.
- Added immutable/runtime-validated inventory, request, metrics, status, and
  result models over M8-E `DocumentChunkSetSummary` inputs, including exact
  nested summary revalidation, outcome/count/digest invariants, and sanitized
  atomic failures.
- Added deterministic read-only propagation for unchanged/changed/removed
  documents, chunk hash/ID diffs, explicit inventory states, and config-hash
  invalidation cascades through the M9-D1 tombstone projector. No exporter,
  store, checkpoint, network, clock, metadata, Qdrant, or embedding side
  effects are present.
- Validation: focused `90 passed`; M9-D1/M8-E `54 passed`; bounded M9-A/B/C
  `284 passed, 2 skipped, 1 deselected` (one external tokenizer-asset case);
  architecture `87 passed`; compileall/diff-check passed.
- Review artifacts: `.codex-workflow/20260805-m9d2/12-review-final.md`
  records the pre-fix P2 coverage finding; `.codex-workflow/20260805-m9d2/16-review-final.md`
  is the fresh final independent review.
- Residual boundary: M8-AC real mini-corpus acceptance remains
  `pending_external_input`; M10 full-snapshot work has not started.

## Current Execution Boundary

The bounded M7-C5 durability-first inventory and M7-D5 raw-generation
replay/checkpoint stages are complete with their independent gates. Stage A's
in-memory batch orchestration/checkpoint-resume reference slice is also
complete and independently reviewed `PASS`; it provides runtime-validated
batch contracts, deterministic partitioning, lease fencing/reclaim, retry and
resume accounting, bounded resource budgets, and adversarial tests. SQLite v2,
production transport, RSS sampling, real-scale validation, and the 100k
performance gate remain deferred; no 100k scale PASS is claimed.

## Stage A Bounded Batch Orchestration State

- Status: complete and independently reviewed `PASS`.
- Review workflow artifacts: `.codex-workflow/20260805-scale-ocr/17-scale-fix3-plan-final.md`,
  `.codex-workflow/20260805-scale-ocr/21-scale-fix4-plan-final.md`,
  `.codex-workflow/20260805-scale-ocr/25-scale-fix5-plan-final.md`,
  `.codex-workflow/20260805-scale-ocr/29-scale-fix6-plan-final.md`,
  `.codex-workflow/20260805-scale-ocr/33-scale-fix7-plan-final.md`, and fresh
  review `.codex-workflow/20260805-scale-ocr/35-scale-fix7-independent-review.md`.
- Implementation is intentionally bounded to an in-memory/reference slice.
  It does not replace the durable SQLite checkpoint store or establish a live
  crawl/10k/100k acceptance gate.
- Validation: focused Stage A suite `20 passed` (domain-inclusive review run
  `23 passed`); `python -m compileall -q src tests` passed; `git diff --check`
  passed.

## Stage B Durable Batch Sidecar State

- Status: complete and independently reviewed `PASS`.
- Added additive `batch_state.sqlite3` persistence for the Stage A batch port,
  bound to the canonical workspace/run/generation/config/inventory and full
  ordered occurrence stream. It shares the existing M7 writer lock without
  nested acquisition, preserves exact-v1 bytes/catalog, supports durable CAS
  claim/renew/commit/fail/requeue, retry history, terminal fencing, pending
  enumeration, and deterministic reopen/resume.
- Review artifacts: `.codex-workflow/20260806-scale/03-stage-b-plan-final.md`,
  `.codex-workflow/20260806-scale/07-stage-b-fix-plan-final.md`,
  `.codex-workflow/20260806-scale/11-stage-b-fix2-plan-final.md`,
  `.codex-workflow/20260806-scale/15-stage-b-fix3-plan-final.md`,
  `.codex-workflow/20260806-scale/19-stage-b-fix4-plan-final.md`, and fresh
  review `.codex-workflow/20260806-scale/21-stage-b-fix4-independent-review.md`.
- Validation: sidecar `36 passed`; Stage A/M7 `23 passed`; M7 checkpoint/
  architecture regressions `161 passed, 12 skipped`; compileall and
  diff-check passed.
- Boundary: this is durable checkpoint infrastructure only. It does not add
  live transport, raw/export/chunk publication, RSS sampling, or 1k/10k/100k
  scale evidence; no `100k PASS` is claimed.

## Bounded Synthetic Scale Validation State

- Status: 1,000-page synthetic validation complete and independently reviewed
  `PASS`; 10,000-page measurement remains pending.
- Fix 4 evidence: `.codex-workflow/20260806-scale-validation/scale-validation-fix4-1000.json`.
  Fresh independent review: `.codex-workflow/20260806-scale-validation/21-fix4-independent-review.md`.
- The evidence covers full control/retry/terminal ledgers, checkpoint metrics
  and pending order, D-H fault/reopen cases, non-vacuous replay bounds,
  memory/SQLite parity, and `15/15` malformed side-effect checks.
- Validation: independent 1,000-page harness exit `0`; focused batch/SQLite
  suite `59 passed`; compileall and diff-check passed.
- Boundary: this is synthetic-only evidence. It does not close the 10k/100k,
  RSS, live transport, M8-AC real-corpus, M10 real-POC, or OCR engine gates.

## M9-A4 OCR Productionization Plan State

- Plan reviewed and finalised in `.codex-workflow/20260806-scale-ocr/03-m9a4-plan-final.md`.
- Contract/policy seam is the next bounded implementation stage; actual OCR
  activation remains `pending_external_input` until an engine approval record
  identifies the engine/runtime/model/build, offline/network policy, limits,
  and sanitized acceptance evidence. No engine is guessed or claimed
  production-ready.

## M10-A Wire Contract and Trusted Input Models

- Status: complete and independently reviewed `PASS`.
- Added additive runtime-validated M10 models for approved Confluence scope/
  exclusions, media policy, trusted normalized profile identity, request,
  metrics, projection, result status matrix, and generic quality-report input.
- Bound config hash to the M6G canonical normalized profile preimage and
  `ChunkingProfile.chunker_version`; rejected forged fields, strict-RFC3339
  violations, unsafe/reparse dataset roots, impossible counters, and malformed
  stream/source-scope values before dependencies.
- Validation: focused `23 passed`; M6G compatibility `37 passed`; compileall/
  diff-check passed. Final independent review is `VERDICT: PASS` in
  `.codex-workflow/20260805-m10/17-m10a-review-3.md`.
- Residual boundary: no exporter, CLI, orchestration, or real full-snapshot
  invocation is included; M10-B is now complete, M10-C is next, and M8-AC remains
  `pending_external_input`.

## M10-B Trusted Multi-Source Composition

- Status: complete and independently reviewed `PASS`.
- Added typed Confluence/Git handoffs and an all-or-nothing in-memory
  composition boundary. Canonical shared Foundation schemas are authoritative;
  injected validators are isolated observers and cannot bypass validation.
  Source ownership, page/source-version and Git commit/path provenance, ACL
  inheritance, relation target grammar, media budget/raw-content provenance,
  symbol linkage, sync identity/version/cardinality, deterministic ordering,
  exact metrics, and empty initial tombstones are enforced before projection.
- Added sanitized application failures, callable adapter/validator checks,
  forged result guards, and adversarial malformed-input coverage.
- Validation: focused M10-A/B `51 passed`; bounded M9 `120 passed`; M6G
  compatibility `37 passed`; architecture `88 passed`; compileall and
  diff-check passed. Final fresh review is
  `.codex-workflow/20260805-m10/37-m10b-fix3-review-final.md` with
  `VERDICT: PASS`.
- Residual boundary: no CLI/publication or real full-snapshot invocation is
  included; M10-D and M10-E remain pending and M8-AC remains
  `pending_external_input`.

## M10-C Cross-Stream Projection and Generic Completion

- Status: complete and independently reviewed `PASS`.
- Added additive `m10_quality` completion to the staging completer while
  preserving the legacy one-page/M6G path. Generic mode performs strict
  duplicate-key/non-finite JSON parsing, canonical schema validation on
  defensive copies, exact eight-stream counts, source-scope equality, actual
  relation/ACL/media/symbol/sync/tombstone metric checks, and deterministic
  sanitized twelve-section reporting with no-clobber cleanup.
- The independent review found unsafe profile strings, wrong path runtime
  side effects, and blank JSONL acceptance. A bounded fix added strict ASCII
  profile identifiers, concrete platform `Path` validation before method
  calls, and blank-line rejection, with adversarial coverage.
- Validation: focused `50 passed, 1 skipped`; M6G
  completer/writer/publisher/one-page `118 passed, 8 skipped`; architecture
  `88 passed`; compileall/diff-check passed. Final independent review is
  `.codex-workflow/20260805-m10/51-m10c-fix-independent-review-final.md` with
  `VERDICT: PASS`.
- Residual boundary: M10-E real full-snapshot evidence remains
  `pending_external_input`; M8-AC real mini-corpus remains
  `pending_external_input`.

## M10-D/E CLI, Publication, and Synthetic Acceptance

- Status: bounded implementation complete and independently reviewed `PASS`.
- Added an offline sanitized CLI and infrastructure wiring over the existing
  M3 staging writer, completer, and publisher seams. Publication performs
  strict ten-file readback, deterministic digesting, no-clobber preflight, and
  rollback that restores the exact prior pointer/final state after acceptance
  failure.
- Acceptance validates defensive copies and detects validator mutation of
  parsed records or published bytes. Non-integer `SystemExit` payloads and
  digest/filesystem failures are sanitized at the public boundary.
- Synthetic acceptance proves deterministic ten-file output and repeatability;
  no network, credentials, raw/runtime data, or real snapshot was used.
- Validation: focused `40 passed`; M10-A/B/C `98 passed, 6 skipped`; M6G `37
  passed`; M8/M9 `125 passed`; architecture `89 passed`; compileall and
  diff-check passed. Fresh independent review is
  `.codex-workflow/20260805-m10/62-m10de-fix-independent-review-final.md` with
  verdict `PASS`.
- Residual boundary: real M10 full-snapshot evidence remains
  `pending_external_input`; M8-AC real mini-corpus remains
  `pending_external_input`.

## Confluence Relation/Media Context Closeout

- Status: bounded implementation started.
- Added `MaterializeConfluenceMediaRelations` as a post-ACL generic relation
  stage. It converts normalized media intents into schema-valid deterministic
  `embeds_media` RelationRecords, resolves matched attachments, emits stable
  `unresolved_target` attachment markers for missing references, and appends
  relation IDs to the owning page and its chunks.
- The stage enforces page ownership, media parent consistency, duplicate IDs,
  schema validation, and impossible status/count combinations. It deliberately
  leaves the existing Jira relation path unchanged and emits no
  `attachment_text` chunks, matching v7.4 D20.
- Validation: focused media/materialization suite `17 passed`; compileall and
  `git diff --check` passed.
- Remaining closeout: wire this stage into the real Confluence/M10 adapter,
  add `includes_page`/`links_to_page` resolution, and run the real bounded M10
  snapshot gate. OCR engine activation remains a separate external-input gate.

## Foundation Goal F1 Progress

- Status: bounded implementation complete; real M10 evidence remains pending.
- `ConfluencePageSetResult` now preserves an immutable per-page
  `reference_intents_by_page` side stream and includes it in canonical replay
  bytes; `ProcessConfluencePageSet` populates it instead of dropping reference
  provenance.
- The normalizer now emits `page_link` intents for positively identified
  Confluence page URLs. The generic media/reference materializer can emit
  `includes_page` and `links_to_page` records with deterministic unresolved
  page markers, in addition to `embeds_media`.
- Validation: focused F1 regression `74 + 41` tests passed; compileall and
  `git diff --check` passed.
- The generic stage is wired into the concrete Confluence M10 adapter; real
  source execution remains an external gate.
- M10 now validates resolved media parent ownership, resolved page relation
  ownership, and relation-ID references when generic relation streams are
  present; the legacy Jira-only fixture path remains compatible.

## Foundation Goal F2 Progress

- Status: bounded producer/projection and adapter integration complete; real
  source execution remains pending.
- Added `SyncStateRecordBuilder` and `BuildSyncStateSnapshot` for deterministic
  page/attachment/file/repository rows from emitted document/media streams.
- The builder validates entity type, status, timestamps, hashes, schema shape,
  duplicate IDs, source ownership, and impossible runtime inputs before any
  injected validator is used.
- Validation: sync-state/use-case focused suite `13 passed`; record-builder
  suite `177 passed`; application-boundary suite `26 passed`; compileall and
  `git diff --check` passed.
- Concrete M10 handoff assembly derives sync rows from emitted page,
  attachment, file, and repository streams. Skipped media remain explicit in
  the media policy/status contract.

## Foundation Goal F3 Progress

- Status: bounded handoff assembly and concrete source-adapter boundaries
  complete; real source execution remains pending.
- Added `AssembleConfluenceM10Handoff` and `AssembleGitM10Handoff`. These
  assemble trusted materialized streams and derive sync rows through the F2
  projection instead of accepting manually injected sync-state dictionaries.
- Validation: M10 composition/application suite `15 passed`; focused F2 suite
  remains green; compileall and `git diff --check` passed.
- `ConfluenceM10Adapter` and `GitM10Adapter` sanitize provider output,
  assemble handoffs, derive sync rows, and now carry optional delta tombstones.
  Provider ports still require operator-supplied real source inputs.
- Adapter/composition acceptance now derives the Git repository sync row with
  the pinned commit version, matching M10 provenance validation.

## Foundation Goal F4 Progress

- Status: M8-AC real mini-corpus gate complete; bounded media orchestration is
  implemented; real OCR activation and bounded media corpus acceptance remain
  external approval gates.
- Added `ProcessConfluenceMediaBatch` to process materialized attachments
  atomically, sort assets deterministically, preserve extraction-detail groups,
  and report sanitized capability failures without partial output.
- The M8-AC aggregate receipt above was verified from the operator-supplied
  corpus without copying raw pages or credential evidence into the repository.
  OCR engine activation still requires the approved engine/runtime/model
  artifact.
- Added a strict sanitized F4/F7 operator CLI for JSON metadata envelopes;
  duplicate keys, raw/extra fields, invalid types, oversized input, and failed
  gate status are rejected without echoing paths or payload values.
- Validation: media batch focused suite `4 passed`; existing M9 media tests and
  compile/diff checks remain green.

## Foundation Goal F5-F7 Progress

- F5: full-snapshot exporter, publication, readback, and deterministic
  synthetic acceptance are complete; bounded real Confluence/Git snapshot
  evidence is still pending.
- F6: delta projection, bounded M10 second-sync orchestration, tombstone
  cascades, ACL-only re-emission intents, prior-target membership checks,
  recursive strict readback, and full-to-delta publisher wiring are complete.
  A real second-sync run is still pending.
- F7: scale gate models/evaluator and production-transport enforcement are
  complete; 10k synthetic repeatability passed, while 100k and sanitized real
  production evidence remain pending.
- Operator evaluation CLI validation: `10 passed` focused; F4/F7 evaluator and
  CLI suite `16 passed` in the current workspace.
- Verification on 2026-08-08: `3199 passed, 40 skipped` with the pinned local
  tokenizer bundle; M10 delta/readback focused suite `12 passed`; published
  snapshot readback now rejects non-UTF-8 quality sidecars, incomplete sync
  closures, and cross-type tombstone targets.

## M11 PLM Read-Only Ingestion (HOLD)

- Status: deferred by owner while Confluence closeout is the active priority.
- No PLM MCP server/tools or sanitized real response fixtures are available in
  the current execution environment.
- No PLM crawler, adapter, response schema, or bulk-download behavior is
  implemented or authorized.
- Resume entry condition: sanitized read-only evidence for the documented PLM
  tools, including representative success/error responses and enough repeated
  calls to establish pagination/truncation, identity, timestamp, attachment,
  authorization, permission, and retry semantics.

## W6 URL Packet and Draw.io Mermaid Integration

- Status: bounded implementation integrated and locally verified; real W6
  completion gates remain pending.
- The portable product tree from the main-machine snapshot was transferred by
  an owner-approved exact-content overlay. The scoped tracked file set covered
  configuration templates, product config/contracts, demo/docs/MCP, packaging,
  scripts, source, and tests while excluding `.env`, `data`, raw/runtime
  artifacts, `.local_ai` provenance, and patch-transfer material. Exact source
  content equivalence passed for all 664 transferred files before local
  integration corrections; local-only tracked files were retained.
- The URL operator supports approved full and short Confluence URL forms,
  bounded durable phase sequencing, unique compatible resume, aggregate
  progress, strict publication, explicit partial text-demo publication, and
  `LATEST.txt`-last replay semantics. Indexing, Presentation/API, demo UI,
  retrieval, eval, and their required portable support files are present in the
  unified tree.
- Parsed Draw.io assets now produce searchable `content_kind: diagram` chunks.
  Strict packet export can also read the verified raw XML and emit bounded
  Mermaid `.mmd` files, including node labels, edge labels, and container
  subgraphs. The URL packet verifier accepts only a counted optional
  `diagrams/` directory of bounded UTF-8 `.mmd` files; explicit partial mode
  rejects diagram output.
- Adversarial coverage rejects wrong runtime types, unsafe/malformed XML,
  duplicate IDs, parent cycles, impossible cell flags, inconsistent raw URI
  hashes, Mermaid count mismatches, and partial packets carrying diagrams.
- Validation on 2026-08-18: focused Foundation/Indexing integration `239
  passed`; URL/packet/Draw.io focused regression after integration correction
  `163 passed`; scoped tree-equivalence check passed. Presentation collection
  requires the declared Qdrant runtime dependency set; the current local Python
  environment lacks `grpc`, so that environment gate remains to be rerun after
  dependency installation.
- Remaining W6 boundary: controlled real Root-1/HQ runs, bounded automatic
  restart supervision, recurring isolated scopes, real W4 full/delta evidence,
  SnapshotReady delivery, Indexing activation/acknowledgement, and I5
  end-to-end acceptance are not claimed by this integration.
