# M10-B Implementation

Implemented the bounded typed-adapter and in-memory composition seam from the
approved M10 plan.

## Changes

- Added `M10ConfluenceHandoff` and `M10GitHandoff` with exact runtime field
  checks, generation/commit identity, defensive record copies, and sanitized
  error tuples.
- Added injected `M10ConfluenceAdapter`/`M10GitAdapter` protocols.
- Added pure `compose_m10_projection` validation for provenance drift,
  duplicate identities, source ownership, deny-safe ACL tags, relation
  resolution policy, media parent/provenance/status policy, symbol linkage and
  Git line provenance, sync-state linkage, deterministic stream ordering, and
  tombstone-empty initial snapshots.
- Added `ComposeM10Snapshot` application boundary with atomic adapter calls and
  sanitized `M10CompositionFailure` categories; invalid requests are rejected
  before dependency calls.
- Added adversarial model/use-case coverage, including wrong runtime objects,
  provenance drift, ACL gaps, duplicate IDs, wrong handoffs, adapter failures,
  and zero-call invalid-request behavior.
- Corrected `M10SnapshotRequest.dataset_root` validation to accept the concrete
  Windows `Path` subclass while retaining absolute/plain-directory/symlink
  checks.

## Validation

```text
python -m pytest -q tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py tests/foundation/domain/models/test_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-focused
35 passed in 0.40s

python -m compileall -q src/knowledgenexus/foundation/domain/models/m10_composition.py src/knowledgenexus/foundation/application/use_cases/compose_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py
passed

git diff --check
passed (line-ending warnings only)
```

No exporter, completer, CLI, roadmap/state, connector, network, or operator
run was added. No commit or push was performed.
