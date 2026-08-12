# M10-B Fix2 Implementation

Implemented the approved fix2 plan from `30-m10b-fix2-plan-final.md` for the
findings in `27-m10b-review-final.md`.

## Changes

- Kept the injected validator seam and added a canonical shared
  `FoundationSchemaValidator` path. Each of the seven non-tombstone streams is
  canonical-validated first on an untouched deep copy, then passed to the
  injected validator on a separate copy; mutation or exceptions fail closed,
  while a third untouched copy is projected. Initial tombstones remain empty.
- Added source ownership checks before merged-stream validation: Confluence
  owns page/chunk/ACL/media/relation/sync rows; Git owns document/chunk/ACL/
  symbol/sync rows; cross-source streams and sync identities are rejected.
- Applied POSIX path validation to Git documents, chunks, and symbols.
- Enforced external target grammar for all unresolved relation types and
  rejected whitespace/`unknown`/`none`/`null`/`unresolved` placeholders;
  resolved targets must be emitted.
- Sanitized all application construction/composition exceptions and retained
  exact forged-result/adapter-callability guards.
- Added adversarial coverage for canonical/injected validator mutation and
  bypass, constructor failure, missing/extra records, source ownership,
  Git path traversal/backslashes, unresolved target placeholders, sync
  ownership, and zero adapter calls.

## Validation

```text
python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix2-focused-final
49 passed in 0.74s

python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix2-m9
120 passed in 0.67s

python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix2-m6g
37 passed in 1.43s

python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix2-arch
88 passed in 1.38s

python -m compileall -q src tests
passed

git diff --check
passed (line-ending warnings only)
```

No exporter, completer, CLI, roadmap/state, connector, network, or operator
run was changed. No commit or push was performed.
