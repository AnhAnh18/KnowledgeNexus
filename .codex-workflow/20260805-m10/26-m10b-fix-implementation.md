# M10-B Fix Implementation

Implemented the approved fix plan from `24-m10b-fix-plan-final.md` after the
independent review findings in `19-m10b-review-1.md`.

## Changes

- Added the injected `M10SchemaValidator` protocol and defaulted
  `ComposeM10Snapshot` to the shared `FoundationSchemaValidator`; construction
  rejects non-callable adapters/validators.
- Schema-validated isolated deep copies for all seven non-tombstone streams:
  `CanonicalDocument`, `ChunkRecord`, `RelationRecord`, `ACLRecord`,
  `MediaAsset`, `SymbolRecord`, and `SyncStateRecord`. Validator mutation and
  arbitrary exceptions fail closed without altering projection inputs.
- Tightened handoff/result exact-field and forged-instance checks.
- Enforced Confluence selected-page ordering/source versions, Git
  repo/branch/commit and POSIX path provenance, ACL cardinality/inheritance,
  exact deny-safe Git ACL tags, duplicate identities, and deterministic stream
  ordering.
- Enforced all relation resolution statuses and explicit unresolved Jira target
  markers; rejected fabricated/contradictory targets.
- Enforced media attachment policy/budget, parent/source/version linkage,
  paired raw/content provenance and attachment/hash URI equality; corrected
  processed/failed metrics.
- Enforced Git symbol file/commit/line-span/chunk linkage and active sync-state
  identity/source/entity/version/status/cardinality. Initial tombstones remain
  exactly empty.
- Preserved the existing Windows `Path` compatibility correction in
  `m10_snapshot.py`.
- Expanded focused fixtures/tests to schema-valid records and adversarial
  validator, provenance, ACL, relation, media, symbol, sync, forged-result,
  adapter, and zero-call cases.

## Validation

```text
python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-focused-final
42 passed in 0.55s

python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-m9
120 passed in 0.82s

python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-m6g
37 passed in 1.60s

python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10b-arch
88 passed in 1.59s

python -m compileall -q src tests
passed

git diff --check
passed (line-ending warnings only)
```

No exporter, completer, CLI, roadmap/state, connector, network, or operator
run was changed. No commit or push was performed.
