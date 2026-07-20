# Implementation State

## Current Milestone

M6 - M6-0 page-fetch live evidence has been collected and approved by the
operator on the connected primary machine; this checkout has synchronized that
approved sanitized conclusion only. M6A (fetch and preserve one raw page) is the
next implementation task and has not started. M5C-1 offline smoke harness is
implemented and offline-tested and awaits independent review; M5C-2, the live
inventory run, is still pending on the Confluence-accessible machine. No live
run was performed from the Codex machine.

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

## Next Planned Task

M6A - fetch and preserve exactly one raw production Confluence page, as a review
stack (`[M6A-A]` raw-byte transport capability, `[M6A-B]` deterministic atomic
raw page store, `[M6A-C]` one-page use case plus adapter integration and operator
entrypoint, `[M6A-D]` final regression tests and durable state update), keeping
the lettered commits per repository convention. M6A adds a `get_bytes()`
capability to the approved transport additively, stores the exact response bytes
at `<raw_root>/confluence/pages/<page_id>.json` (default `raw_root` = `data/raw`,
gitignored) with a raw `sha256(exact_bytes)` and atomic same-directory
replacement, and reuses the M5C credential/entrypoint convention. It must not
normalize, chunk, interpret ACL, fetch restrictions or attachments, or start
M6B. The 8 MB response-size guard stays enforced and injectable; a page over the
limit must fail closed. M5C-2 (live inventory smoke) also remains pending on the
Confluence-accessible machine.

### Deferred M5C-2 note

M5C-2: on the Confluence-accessible machine, follow
`docs/runbooks/M5C_CONFLUENCE_INVENTORY_SMOKE.md` and run one small real
inventory against the same small M5B-0 test root (8 descendants) with
`page_size = 2` and `max_search_pages = 10`. That run is the first live
confirmation of `expand=space,version`. Do not point the first run at the large
production root and do not silently raise `max_search_pages`: a
`pagination_limit` exit means the chosen root is too large for a smoke run.
Copy back only `m5c_smoke_summary.json` plus a manually sanitized completion
notice; the real reports stay on that machine. Then inspect the report locally
to choose explicit excluded subtrees before M6.
