# M10-B Fix3 Implementation

Implemented the approved canonical-validator bypass fix from
`34-m10b-fix3-plan.input.md`.

## Changes

- Canonical schema validation now requires the exact shared concrete
  `FoundationSchemaValidator`; no-op fakes and subclasses are rejected before
  adapter calls. The injected validator remains an isolated observer and
  cannot replace canonical validation.
- Preserved canonical-first/injected-second validation on separate copies,
  mutation detection, defensive projection copies, atomic failure behavior,
  and sanitized constructor/application exceptions.
- Added adversarial tests for no-op validators on both seams with malformed
  extra-field records, canonical subclass rejection, canonical mutation, and
  zero adapter calls.

## Validation

```text
python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix3-focused-final
51 passed in 0.74s

python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix3-m9
120 passed in 0.69s

python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix3-m6g
37 passed in 1.34s

python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10b-fix3-arch
88 passed in 1.35s

python -m compileall -q src tests
passed

git diff --check
passed (line-ending warnings only)
```

No exporter, completer, CLI, roadmap/state, connector, network, or operator
run was changed. No commit or push was performed.
