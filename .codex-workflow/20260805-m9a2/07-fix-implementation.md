# M9-A2 Review Fix Implementation

Implemented the bounded fixes from `06-fix-plan.md` and the additional
independent-review cases for forged envelope/artifact instances, replay scan
ordering, directory TOCTOU checks, and hardlink rejection.

## Production changes

- Fetch/store port errors now carry only closed category values and expose
  sanitized representations.
- The use case rebuilds and validates budgets, HTTP observations, and returned
  artifacts before field access; unexpected fetch/store exceptions map to
  stable failure categories.
- The raw store rebuilds envelopes and budgets, serializes cumulative budget
  accounting per data root, scans before replay, bounds iterative tree scans,
  validates root/parent directory identity across scan-to-publication, rejects
  hardlinked regular files, canonicalizes equivalent root lock keys, and maps
  scan failures to `raw_artifact_invalid`.
- Public raw-artifact representations no longer expose byte counts.
- Focused adversarial tests cover forged instances, exception sanitization,
  replay pollution, scan failures, concurrent budget accounting, and category
  allowlists.

## Validation

- `uv run python -m pytest -q tests/foundation/domain/models/test_media_body_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/infrastructure/raw_store/test_confluence_raw_attachment_store.py tests/architecture/test_m9a2_attachment_body_boundary.py --basetemp=.pytest-m9a2-fix6`
  -> `37 passed, 2 skipped`.
- `uv run python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/infrastructure/raw_store/test_confluence_raw_restriction_store.py tests/foundation/domain/models/test_media_body_materialization.py tests/foundation/infrastructure/raw_store/test_confluence_raw_attachment_store.py tests/architecture/test_m9a2_attachment_body_boundary.py --basetemp=.pytest-m9a2-reg2`
  -> `48 passed, 3 skipped`.
- `python -m compileall -q src tests` -> passed.
- Scoped `git diff --check` -> passed.

Independent re-review remains required before ledger updates, commit, and
push.
