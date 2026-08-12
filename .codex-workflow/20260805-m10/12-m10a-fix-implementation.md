# M10-A Boundary Validation Fix Implementation

Implemented only the reviewed M10-A model/test hardening scope.

## Changes

- Added exact dataclass-field guards to every public M10-A model, rejecting
  forged frozen instances, missing fields, forbidden extras, and wrong exact
  runtime types before attribute access.
- Revalidated nested scope, exclusion, media, run, profile, metrics, and
  result values at public boundaries.
- Centralized strict RFC3339 validation requiring timezone (`Z` or numeric
  offset), rejecting naive/date-only/invalid-calendar values while preserving
  the original timestamp bytes.
- Rejected Windows reparse-point dataset roots via `st_file_attributes`, in
  addition to symlink/non-directory/unsafe-root checks.
- Expanded focused adversarial tests with forged nested models and timestamp
  acceptance/rejection matrices.

## Validation

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10a-fix
22 passed

python -m compileall -q src tests
passed

git diff --check
passed (line-ending warning only)
```

No exporter, CLI, orchestration, roadmap/state, or M8/M9 files were changed.
No commit or push performed.
