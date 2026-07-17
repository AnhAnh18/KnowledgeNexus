# M3C ManifestRecordBuilder Review Summary

## Patch Type

Full/squashed patch for M3C ManifestRecordBuilder.

Apply after the accepted M3B DatasetVersionGenerator state.

## Files Changed In Code Patch

- `src/knowledgenexus/foundation/domain/records/manifest_record_builder.py`
  - Adds the pure schema-shaped Manifest record builder.
- `src/knowledgenexus/foundation/domain/records/__init__.py`
  - Exports `ManifestRecordBuilder` from the records package.
- `tests/foundation/domain/records/test_manifest_record_builder.py`
  - Adds focused tests for schema-valid manifests, optional fields, counts,
    source scopes, copy behavior, lightweight validation, and schema-boundary
    validation.

## Workspace-Only Files Not Included In Code Patch

- `.local_ai/IMPLEMENTATION_STATE.md`
- `.local_ai/ROADMAP.md`
- `.local_ai/review/m3c-manifest-record-builder-review-summary.md`
- `.local_ai/review/m3c-manifest-record-builder.patch`

## Public API

```python
ManifestRecordBuilder.build(
    *,
    dataset_version: str,
    export_mode: str,
    generated_at: str,
    config_hash: str,
    chunker_version: str,
    schemas_version: str,
    counts: Mapping[str, int],
    base_dataset_version: str | None = None,
    source_scopes: Mapping[str, object] | None = None,
) -> dict[str, object]
```

All version, time, hash, count, and source-scope values are caller-provided.

## Schema Findings

Required Manifest fields:

- `schema_version`
- `dataset_version`
- `export_mode`
- `generated_at`
- `config_hash`
- `chunker_version`
- `schemas_version`
- `counts`

Optional Manifest fields:

- `base_dataset_version`
- `source_scopes`

Other schema facts:

- `additionalProperties` is `false`.
- `schema_version` is const `"1.0"`.
- `dataset_version` is a non-empty string.
- `base_dataset_version` accepts string or null but is not required.
- `counts` is an object with arbitrary keys and non-negative integer values.
- `source_scopes` is an optional free-form object.

## Optional-Field Policy

- `base_dataset_version=None` is omitted.
- Caller-supplied `base_dataset_version` strings are preserved exactly,
  including the empty string because the current schema allows string without
  `minLength`.
- `source_scopes=None` is omitted.
- Explicit `source_scopes={}` is preserved.

## Counts Policy

- `counts` is required and caller-provided.
- `counts` must be a mapping.
- Count keys must be strings.
- Count values must be actual integers.
- `bool` count values are rejected.
- Negative integers are rejected.
- Count names are not hardcoded, sorted, renamed, or inferred.
- Counts are copied into a plain dict.

## Source Scopes Policy

- `source_scopes` must be a mapping when provided.
- Top-level source-scope keys must be strings.
- The top-level mapping is materialized into a plain dict.
- Nested dictionaries and lists are deep-copied to isolate caller and record
  mutations.
- No source-scope schema or connector-derived normalization is introduced.

## Base Dataset Version Boundary

The schema description says `base_dataset_version` is required for delta
exports, but the current JSON Schema does not encode that cross-field rule.

M3C does not enforce:

- `export_mode == "delta"` requires `base_dataset_version`;
- delta ordering;
- previous snapshot lookup;
- `LATEST.txt` reading.

Those semantics belong to later snapshot orchestration.

## Intentionally Not Implemented

- No manifest file writing.
- No `JsonlRecordWriter` changes.
- No `DatasetVersionGenerator` changes.
- No current-time acquisition or datetime formatting.
- No config hashing.
- No chunker profile selection.
- No schema-version discovery.
- No count calculation from records or files.
- No source-scope extraction.
- No directory scanning.
- No snapshot directory creation.
- No staging directories.
- No full-snapshot or delta orchestration.
- No `LATEST.txt`.
- No `quality_report.md`.
- No FoundationSchemaValidator calls inside the builder.
- No schema or contract changes.
- No connector, indexing, retrieval, chat, Qdrant, or Gauss behavior.

## Test Command And Result

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/foundation/infrastructure/exporters tests/shared -q
295 passed in 3.31s
```

Focused test:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records/test_manifest_record_builder.py -q
43 passed in 0.79s
```

## Patch Validation

```text
git apply --reverse --check .local_ai/review/m3c-manifest-record-builder.patch
passed
```

## Schema Differences Discovered

- `generated_at` is defined with JSON Schema `format: date-time`, but the
  current validator setup did not reject a malformed date-time string during
  M3C tests. M3C still leaves generated_at formatting/validation outside the
  builder and does not duplicate date-time validation.
