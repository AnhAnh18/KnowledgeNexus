# M3E FullSnapshotStagingCompleter Review Summary

## Patch Type

Full/squashed M3E patch. Apply after the approved full/squashed M3D patch.

## Files Changed In Code Patch

- `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_completer.py`
- `src/knowledgenexus/foundation/infrastructure/exporters/__init__.py`
- `tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py`

Local-only steering and review files are intentionally excluded from the code
patch.

## Public API

```python
FullSnapshotStagingCompleter.complete(
    *,
    staging_path: Path,
    validator: FoundationSchemaValidator,
) -> dict[str, object]
```

The return value is the validated plain Manifest dict loaded from
`manifest.json`.

## Purpose

M3E adds a deterministic human-readable `quality_report.md` sidecar to an
already successful M3D machine-readable staging directory. The report is for
developer/operator inspection and is not the machine contract.

## Pre-Completion File Set

M3E requires exactly these nine regular, non-symlink files:

- `documents.jsonl`
- `chunks.jsonl`
- `relations.jsonl`
- `acl.jsonl`
- `media_assets.jsonl`
- `symbols.jsonl`
- `sync_state.jsonl`
- `tombstones.jsonl`
- `manifest.json`

Missing files, extra files, directories, symlinks, temp files, and a
pre-existing `quality_report.md` are rejected without repair or deletion.

## Manifest Validation

- Reads `manifest.json` as UTF-8 JSON.
- Requires one top-level JSON object.
- Validates the object as `Manifest` through `FoundationSchemaValidator`.
- Propagates JSON parsing and Foundation schema validation errors.
- Does not mutate or rewrite `manifest.json`.

## Producer Invariants

After schema validation, M3E requires:

- `export_mode == "full_snapshot"`.
- `base_dataset_version` is absent.
- `counts` contains exactly `documents`, `chunks`, `relations`, `acl`,
  `media_assets`, `symbols`, `sync_state`, and `tombstones`.
- Every count is a non-negative actual integer; bool is rejected.

M3E treats the Manifest counts written from M3D writer results as the source of
truth. It does not reread or recount JSONL records.

## Quality Report Structure

The report has fixed sections and order:

1. `Foundation Export Quality Report`
2. `Snapshot`
3. `Record Counts`
4. `Completion Checks`
5. `Scope`

It preserves Manifest scalar metadata exactly, renders the eight count rows in
fixed order, and claims PASS only for checks M3E actually performed. It omits
`source_scopes` and does not invent semantic or downstream quality metrics.

Serialization is deterministic UTF-8 with `\n` newlines and exactly one final
newline. Output does not depend on time, timezone, hostname, process ID,
filesystem order, dictionary order, staging path, or OS newline convention.

## Final File Set

After report publication, M3E requires exactly the nine machine-readable files
plus `quality_report.md`. Every direct child must be a regular, non-symlink
file.

## Writing And Ownership Policy

- Writes through a same-directory temporary file.
- Closes the temporary file before `Path.replace()` for Windows compatibility.
- Never overwrites a pre-existing report.
- Cleans only its temporary file on write/replace failure.
- Removes only the newly created report when final verification fails.
- Cleanup failure is logged and does not mask the original exception.
- Never deletes staging, JSONL files, `manifest.json`, or unexpected
  caller-owned entries.

The staging path is exclusively owned by the current export workflow.
Completeness verification is not security-grade protection against hostile
concurrent filesystem mutation.

## Contract Difference

Master Spec v7.1 says the final POC quality report contains counts, skips,
failures, and coverage warnings. M3E has no real pipeline evidence for skips,
failures, or coverage, and the task correctly forbids invented claims.

Therefore M3E implements the minimal construction-metadata report and complete
file-set gate. The richer final POC quality report remains deferred until real
producer metrics exist.

## Intentionally Not Implemented

- No final staging-to-snapshot move or rename.
- No dataset-name or final export-path calculation.
- No `LATEST.txt` creation or update.
- No JSONL recounting or checksums.
- No quality scoring, skips/failures synthesis, or coverage analysis.
- No locking, permissions hardening, retries, recovery, async, or concurrency.
- No schema, contract, builder, validator, M3D, or dependency changes.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py -q
26 passed in 3.35s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/shared/contracts/foundation -q
85 passed in 5.38s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
360 passed in 6.51s
```

No formatter, linter, or type checker configuration is present in the
repository, so no new tooling was added.
