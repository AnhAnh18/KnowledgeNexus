# M4 Golden Full-Snapshot Export Review Summary

## Patch Type

Full/squashed M4 patch. Apply after the approved full/squashed M3F patch.

## Files Changed In Code Patch

- `.gitattributes`
- `tests/fixtures/foundation/golden_record_set.py`
- `tests/foundation/integration/test_golden_full_snapshot_export.py`
- `tests/fixtures/foundation/golden_full_snapshot/LATEST.txt`
- Ten committed artifacts under the fixed version directory, including the
  zero-byte `symbols.jsonl` and `tombstones.jsonl`. `LATEST.txt` is at the
  dataset root, outside that version directory.

No production source, dependency file, schema, contract, or `.local_ai` file is
included in the code patch.

The scoped `.gitattributes` rule forces LF checkout only for the committed
golden fixture tree, preventing `core.autocrlf` from changing expected bytes on
Windows.

## Purpose

The committed golden dataset root is a small exact producer-output example and
deterministic regression oracle. It is synthetic test data, not a production
export, semantic benchmark, indexing fixture, or replacement for active schemas.

## Exact Fixture Tree

```text
tests/fixtures/foundation/golden_full_snapshot/
|-- LATEST.txt
`-- v20260714-000000-000000Z/
    |-- acl.jsonl
    |-- chunks.jsonl
    |-- documents.jsonl
    |-- manifest.json
    |-- media_assets.jsonl
    |-- quality_report.md
    |-- relations.jsonl
    |-- symbols.jsonl
    |-- sync_state.jsonl
    `-- tombstones.jsonl
```

## Fixed Metadata

- Dataset version: `v20260714-000000-000000Z`
- Generated at: `2026-07-14T00:00:00.000000Z`
- Config hash: 64 lowercase `a` characters
- Chunker version: `1.2.0`
- Schemas version: `1.0`
- Source scopes: synthetic Confluence space `GOLDEN` and page ID
  `golden-page-001`

The source scopes are present in `manifest.json` and intentionally absent from
`quality_report.md`.

## Record Graph And Counts

| Record type | Count |
|---|---:|
| documents | 1 |
| chunks | 2 |
| relations | 1 |
| acl | 1 |
| media_assets | 1 |
| symbols | 0 |
| sync_state | 1 |
| tombstones | 0 |

The graph follows the M2D topology and uses the existing production builders
and ID generators for Document, Chunk, Relation, ACL, and Confluence attachment
identities. Identifiers, text, Jira key, ACL tags, source scope, media, and
sync-state data are visibly synthetic. The Symbol stream is intentionally empty;
Git/Symbol semantics and production builders remain deferred to M9.

The two wiki chunk texts follow the active `CHUNKING_SPEC`: each has a
breadcrumb prefix, and the code-block chunk retains its Markdown fences and
`cpp` language tag. The serialized text is also the input used for each chunk's
content hash and ID; token-count fixture values were updated with the text.

Coherence checks deserialize the committed published JSONL files before
checking document references from chunks/ACL/media/sync-state, relation
endpoints and chunk relation IDs, chunk ACL compatibility, unique IDs, and
deterministic expected IDs.

## Schema/File Mapping

The acceptance test imports the authoritative M3D mapping:

- `documents.jsonl` -> `CanonicalDocument`
- `chunks.jsonl` -> `ChunkRecord`
- `relations.jsonl` -> `RelationRecord`
- `acl.jsonl` -> `ACLRecord`
- `media_assets.jsonl` -> `MediaAsset`
- `symbols.jsonl` -> `SymbolRecord`
- `sync_state.jsonl` -> `SyncStateRecord`
- `tombstones.jsonl` -> `TombstoneRecord`

No second schema loader or validator was introduced.

## Generation Flow

`generate_golden_full_snapshot()` creates fresh one-pass record streams and
runs:

```text
FullSnapshotStagingWriter
-> FullSnapshotStagingCompleter
-> FullSnapshotPublisher
```

The review-fixed committed fixture was generated into a candidate dataset root
by a temporary one-off pytest test that called this helper. The command used was:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/integration/test_generate_m4_candidate.py -q
1 passed in 0.26s
```

The temporary generator test was deleted immediately afterward and is not part
of the patch. Normal tests generate only under `tmp_path` and never modify the
committed fixture.

For an intentional refresh, first generate a review candidate in a new path:

```text
python -c "from pathlib import Path; from tests.fixtures.foundation.golden_record_set import generate_golden_full_snapshot; p=Path('tests/fixtures/foundation/golden_full_snapshot_candidate'); p.mkdir(parents=True, exist_ok=False); generate_golden_full_snapshot(p)"
```

Review the exact path/byte diff before deliberately replacing the committed
fixture. There is no automatic update mode.

## Comparison And Validation

- Fresh M3 output is compared recursively with the committed fixture.
- Relative entry paths and file/directory kinds must match exactly.
- Every corresponding file must have identical bytes.
- Failures report missing, unexpected, wrong-kind, and byte-different paths.
- The committed Manifest is parsed and validated against `Manifest`.
- Every non-empty JSONL line is parsed as one object and validated against its
  mapped schema.
- No blank JSONL lines are allowed; non-empty files have exactly one final
  newline and empty streams are zero-byte files.
- Actual JSONL records are recounted only in the M4 acceptance test and must
  equal Manifest counts.
- `LATEST.txt`, folder/Manifest version equality, exact ten-file snapshot set,
  report metadata/counts, and source-scope omission are checked.
- Exact exported prose/code text, fenced code preservation, zero-byte Symbol
  output, zero Symbol count, and deterministic media attachment ID are checked.
- M2D graph coherence is checked only after reading and deserializing the
  committed published JSONL records.

## Determinism Proof

Two independent temporary dataset roots generated from fresh one-pass streams
have identical relative path sets and identical bytes for every file, including
`LATEST.txt`.

## Data Boundary

No Confluence/Git/MCP/network/database access occurred. No environment file,
credential, token, internal server address, real page content, or user-specific
absolute path is present in the fixture. No Git or Symbol fixture record is
present.

## Production Changes

None. M4 exposed no production defect and required no M3 API change.

## Contract Differences

None. The active integration contract remains authoritative. The known M3E
minimal-report limitation remains unchanged: richer POC skips, failures, and
coverage warnings still require real pipeline evidence.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/integration/test_golden_full_snapshot_export.py -q
7 passed in 0.50s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/foundation/integration tests/shared/contracts/foundation -q
132 passed in 5.14s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
407 passed in 5.51s

git diff --check
passed with exit code 0; only Git line-ending conversion advisories were emitted

git apply --reverse --check .local_ai/review/m4-golden-full-snapshot-export.patch
passed
```

No formatter, linter, or type checker configuration is present.
