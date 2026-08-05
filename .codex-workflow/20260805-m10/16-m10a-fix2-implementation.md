# M10-A Profile Provenance Fix Implementation

Implemented the reviewed M10-owned profile-preimage and chunker binding fix.

## Changes

- Added immutable `M10ProfileIdentity` carrying the canonical normalized
  embedding/Jira profile preimage and deriving the approved M6G config hash.
- Required and validated that identity on `M10SnapshotRequest`; revalidated
  the exact profile bundle and nested M6G profile fields without modifying M6G
  classes/loaders, and rejected config-hash drift.
- Bound projection chunker versions to `ACTIVE_CHUNKER_VERSION`; added
  `M10SnapshotProjection.from_request` to derive config/generation/chunker
  identity from a validated request and reject mismatches atomically.
- Added forged identity/profile and chunker/tamper tests.

## Validation

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10a-fix2
23 passed

python -m compileall -q src tests
passed

git diff --check
passed (line-ending warning only)
```

No M6G classes/loaders, exporter, CLI, orchestration, roadmap/state, or M8/M9
files were changed. No commit or push performed.
