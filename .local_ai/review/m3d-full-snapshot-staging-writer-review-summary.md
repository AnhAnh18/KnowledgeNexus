# M3D FullSnapshotStagingWriter Review Summary

## Patch Type

Full/squashed patch for M3D. Apply after the approved M3A, M3B, M3C, and M3C.1 patches.

## Files Changed In Code Patch

- `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_writer.py`
- `src/knowledgenexus/foundation/infrastructure/exporters/__init__.py`
- `tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py`

## Public API

`FullSnapshotStagingWriter.write(...) -> dict[str, object]`

The API is keyword-only and accepts:

- explicit `staging_path`
- explicit `FoundationSchemaValidator`
- caller-provided `dataset_version`, `generated_at`, `config_hash`, `chunker_version`, and `schemas_version`
- eight caller-provided record streams
- optional `source_scopes`

It always builds a Manifest with `export_mode="full_snapshot"` and omits `base_dataset_version`.

## Fixed File/Schema Mapping

| File | Schema |
|---|---|
| `documents.jsonl` | `CanonicalDocument` |
| `chunks.jsonl` | `ChunkRecord` |
| `relations.jsonl` | `RelationRecord` |
| `acl.jsonl` | `ACLRecord` |
| `media_assets.jsonl` | `MediaAsset` |
| `symbols.jsonl` | `SymbolRecord` |
| `sync_state.jsonl` | `SyncStateRecord` |
| `tombstones.jsonl` | `TombstoneRecord` |

Also writes `manifest.json`.

## Count-Key Convention

Counts are actual return values from `JsonlRecordWriter`, keyed by JSONL basename:

- `documents`
- `chunks`
- `relations`
- `acl`
- `media_assets`
- `symbols`
- `sync_state`
- `tombstones`

The writer does not count `manifest.json`, `quality_report.md`, directories, bytes, or lines reread from disk.

## Validation Flow

- Each record is copied from generic `Mapping` to a plain `dict`, validated with `FoundationSchemaValidator.validate_record(...)`, then yielded to `JsonlRecordWriter`.
- Streams are consumed once and not materialized.
- Manifest is built after all JSONL files are written successfully.
- Manifest is validated before `manifest.json` is written.

## Staging Ownership Policy

- `staging_path` is explicit and caller-selected.
- `staging_path` must not already exist.
- `staging_path.parent` must already exist.
- M3D creates and owns `staging_path`.
- On success, staging remains for M3E.
- On post-creation failure, M3D best-effort removes the entire owned staging directory without masking the original exception.

## Manifest Writing Policy

`manifest.json` is a single deterministic JSON object:

- UTF-8
- `ensure_ascii=False`
- `sort_keys=True`
- `separators=(",", ":")`
- `allow_nan=False`
- exactly one trailing newline

## Expected Output File Set

Successful staging contains exactly:

- `documents.jsonl`
- `chunks.jsonl`
- `relations.jsonl`
- `acl.jsonl`
- `media_assets.jsonl`
- `symbols.jsonl`
- `sync_state.jsonl`
- `tombstones.jsonl`
- `manifest.json`

The completeness check compares every direct child entry and also requires each
entry to be a regular file. Unexpected directories or symlinks are rejected and
trigger owned-staging cleanup.

## Review Cleanup

- Fixed completeness verification so it no longer filters out unexpected child
  directories before comparing the staging contents.
- Added regression coverage for an unexpected directory created after
  `manifest.json` is written.
- Added regression coverage for strict Manifest serialization failure when a
  schema-valid `source_scopes` value contains a non-JSON-serializable nested
  value.
- Fixed the generic `Mapping` validation path by materializing one plain `dict`
  record at a time before schema validation and writing.
- Added regression coverage with `MappingProxyType` input.
- Wrapped the long staging-writer module import in the test file.

## Intentionally Not Implemented

- No final snapshot directory publishing.
- No atomic staging-to-final move.
- No `LATEST.txt`.
- No `quality_report.md`.
- No delta export or `base_dataset_version`.
- No snapshot overwrite.
- No locking, retry loops, recovery journals, checksums, compression, parallel writes, or async I/O.
- No schema, contract, record-builder, M3A, M3B, M3C, or M3C.1 behavior changes.

## Contract Differences

The active POC export contract requires `quality_report.md` for a complete export, but M3D intentionally constructs only the machine-readable staging snapshot. `quality_report.md` remains deferred to M3E, before atomic finalization or `LATEST.txt`.

The active schemas leave Manifest `counts` keys free-form. M3D uses the approved producer convention that count keys match JSONL basenames.

Sequencing correction after review: because `quality_report.md` is required for
a complete POC export, the next step should make staging contract-complete
before any atomic finalization or `LATEST.txt` update.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py -q
19 passed in 1.14s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/foundation/domain/records tests/shared/contracts/foundation -q
228 passed in 2.23s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
334 passed in 2.70s

git diff --check -- src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_writer.py src/knowledgenexus/foundation/infrastructure/exporters/__init__.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py
passed

git apply --reverse --check .local_ai/review/m3d-full-snapshot-staging-writer.patch
passed
```
