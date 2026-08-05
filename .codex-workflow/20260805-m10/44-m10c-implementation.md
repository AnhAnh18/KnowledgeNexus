# M10-C Implementation

Implemented the approved additive `m10_quality` mode for
`FullSnapshotStagingCompleter` while preserving the legacy one-page and M6G
paths.

## Changes

- Added strict `m10_quality` completion dispatch: exact
  `M10QualityReportInput`, no simultaneous `one_page_quality`, and exact
  concrete shared `FoundationSchemaValidator` before filesystem inspection.
- Added strict duplicate-key/non-finite JSON parsing, canonical validation on
  untouched copies for Manifest and all seven non-tombstone streams, mutation
  detection, defensive rendering copies, exact eight count keys, source-scope
  validation, and initial-empty tombstone enforcement.
- Added actual stream-derived checks for relation status counts, ACL coverage /
  restricted/default-deny counts, media processed/failed/not-processed counts,
  symbol resolution, sync status/entity-type counts, and tombstone counts.
- Added deterministic sanitized twelve-section report rendering in fixed order:
  Snapshot, Active Profiles, Record Counts, Jira Relation Quality, ACL Quality,
  Media Quality, Symbol Quality, Sync State, Tombstones, Completion Checks,
  Publication State, and Scope.
- Preserved no-clobber report creation and owned-report cleanup on final-set
  failure; generic failures are sanitized without changing machine streams.
- Added adversarial generic-mode tests for fake validators, wrong quality
  combinations, count drift, non-empty tombstones, duplicate JSON keys,
  deterministic bytes, sanitization, and pre-existing reports.

## Validation

```text
python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer_m10.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py --basetemp=.codex-workflow/20260805-m10/pytest-m10c-focused-final
42 passed, 1 skipped in 1.14s

python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py tests/foundation/infrastructure/exporters/test_one_page_full_snapshot_exporter.py --basetemp=.codex-workflow/20260805-m10/pytest-m10c-m6g
118 passed, 8 skipped in 2.85s

python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10c-arch
88 passed in 1.39s

python -m compileall -q src tests
passed

git diff --check
passed (line-ending warnings only)
```

No CLI, publisher, writer, roadmap/state, connector, network, or operator run
was changed. No commit or push was performed.
