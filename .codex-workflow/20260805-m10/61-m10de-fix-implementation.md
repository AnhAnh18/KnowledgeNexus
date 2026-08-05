# M10-D/E Fix Implementation

## Scope

Implemented only the four approved findings from `59-m10de-fix-plan-final.md`.
No roadmap/state files, commits, or pushes were made.

## Changes

- Snapshot the pre-publication `LATEST.txt` state and final-version path. If
  post-publication acceptance (including digest calculation) fails, restore the
  exact prior pointer bytes atomically when available, remove a newly advertised
  pointer only when it still contains this run's value, and remove only the
  newly created final directory.
- Acceptance readback now parses bytes captured before validation, validates
  defensive copies, rejects validator mutation, and detects validator changes
  to manifest/JSONL files (including replacement by symlinks/non-files).
- CLI `SystemExit` handling accepts only an exact integer code; all other
  payloads emit sanitized `unexpected` JSON and return exit code `1`.
- Digest calculation is inside post-publication acceptance handling, so hash
  or filesystem failures map to `M10SnapshotExportFailure("acceptance")`.

## Adversarial Tests

Added coverage for report tampering rollback, exact prior pointer restoration,
stateful validator record mutation, validator on-disk tampering, digest
exceptions, and `SystemExit("secret payload")` sanitization.

## Validation

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/application/use_cases/test_export_m10_snapshot.py tests/foundation/cli/test_export_m10_snapshot_cli.py tests/foundation/integration/test_m10_synthetic_acceptance.py tests/architecture/test_application_import_boundary.py --basetemp=.codex-workflow/20260805-m10/61-pytest-m10de-focused
40 passed in 1.19s

$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer_m10.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py --basetemp=.codex-workflow/20260805-m10/61-pytest-m10abc
98 passed, 6 skipped in 2.11s

$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/61-pytest-m6g
37 passed in 1.63s

$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/61-pytest-m8m9
125 passed in 0.91s

$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/61-pytest-architecture
89 passed in 1.62s

python -m compileall -q src tests
completed successfully

git diff --check
completed successfully (only existing LF/CRLF warnings)
```
