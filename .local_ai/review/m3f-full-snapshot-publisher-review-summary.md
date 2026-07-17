# M3F FullSnapshotPublisher Review Summary

## Patch Type

Full/squashed M3F patch. Apply after the approved full/squashed M3E patch.

## Files Changed In Code Patch

- `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_publisher.py`
- `src/knowledgenexus/foundation/infrastructure/exporters/__init__.py`
- `tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py`

Local-only steering and review files are intentionally excluded from the code
patch.

## Public API

```python
FullSnapshotPublisher.publish(
    *,
    staging_path: Path,
    dataset_root: Path,
    validator: FoundationSchemaValidator,
) -> Path
```

The return value is the final snapshot directory derived from the validated
Manifest dataset version.

## Path Preconditions

- `dataset_root` already exists and is a directory.
- `staging_path` already exists, is a directory, is not a symlink, and is a
  direct child of `dataset_root` after path resolution.
- M3F creates neither path and does not support cross-filesystem copying.
- Concurrent publishers and concurrent staging mutation are unsupported.

## Completed Staging Verification

Before publication, staging must contain exactly these regular, non-symlink
files:

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

M3F does not repair, recreate, remove, recount, or rewrite staging contents.

## Manifest And Publisher Invariants

- `manifest.json` is parsed as one UTF-8 JSON object.
- The Manifest is validated through `FoundationSchemaValidator`.
- `export_mode` must be `full_snapshot`.
- `base_dataset_version` must be absent.
- Counts must contain exactly the eight approved keys.
- Counts must be non-negative actual integers; bool is rejected.
- `dataset_version` must match `vYYYYMMDD-HHMMSS-ffffffZ` before it is used as
  a filesystem component.

The final path is derived only as:

```text
dataset_root / manifest.dataset_version
```

Every pre-existing final directory, file, symlink, or dangling symlink is
rejected with no overwrite, merge, deletion, or reuse.

## Directory Publication

After all preflight checks, M3F calls direct same-parent:

```python
staging_path.rename(final_path)
```

There is no `shutil.move`, copy fallback, directory replacement, reservation
directory, or content mutation.

## LATEST.txt

`LATEST.txt` is preflighted before directory rename. It may be absent or an
existing regular non-symlink file; directories and symlinks are rejected.

After the final directory exists, M3F writes a temporary file inside
`dataset_root`, closes it, and atomically replaces `LATEST.txt` with
`Path.replace()`.

Exact bytes:

```text
<dataset_version>\n
```

There is no BOM, quoting, JSON, path, extra whitespace, or trailing blank line.

## Failure States

| Failure point | Staging | Final path | Existing LATEST |
|---|---|---|---|
| Path/file-set/Manifest/invariant preflight | Preserved | Not created | Unchanged |
| Final destination already exists | Preserved | Existing entry untouched | Unchanged |
| Directory rename fails | Preserved where OS rename is atomic | Not created by M3F | Unchanged |
| LATEST temp/write/replace fails after rename | No longer present | Preserved and complete | Old pointer unchanged when replacement did not occur |
| Success | No longer present | Preserved and complete | New dataset version published |

M3F does not roll the final directory back to staging. An unadvertised final
snapshot is an accepted safe partial state and requires explicit operator
action or a future focused recovery task.

## Contract Compatibility

The active integration contract requires
`data/exports/<dataset_name>/<dataset_version>/`, equality between folder name
and `manifest.dataset_version`, and a Windows-safe `LATEST.txt` pointer.

M3F's M3B shape check, same-parent rename, no-overwrite policy, and atomic
pointer replacement are compatible producer-safety rules. No active contract
or schema was changed.

## Intentionally Not Implemented

- No staging construction, Manifest construction, report generation, or JSONL
  validation/recounting.
- No cross-filesystem copy, overwrite, merge, retention, or old-snapshot cleanup.
- No rollback, automatic recovery, retries, locks, leases, or journals.
- No permissions hardening, checksums, signatures, async, or concurrency.
- No delta publication or previous-snapshot lookup.
- No schema, contract, builder, validator, M3D, M3E, or dependency changes.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py -q
40 passed in 3.19s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/exporters tests/shared/contracts/foundation -q
125 passed in 4.57s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
400 passed in 5.51s
```

No formatter, linter, or type checker configuration is present, so no new
tooling was added.
