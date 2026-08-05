# M9-D1 Final Independent Re-review

Review target: current M9-D1 working tree after the second fixes described in
`11-fix2-plan-review.md`, against `02-plan-revised.md` and `AGENTS.md`.

## Findings

- **P1 - Result validation deep-copies untrusted values before rejecting them** - `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:197-203` calls `copy.deepcopy` before `_validate_json_object`. A record containing a wrong-type value with a custom `__deepcopy__` can execute arbitrary side effects and leak an arbitrary exception (for example, `RuntimeError`) instead of failing closed with `TypeError`/`ValueError`. Validate the original record's JSON shape before copying, or otherwise avoid invoking user-controlled copy hooks at this boundary.

- **P1 - Forged frozen model instances with extra attributes are accepted** - `TombstoneTarget.__post_init__`, `TombstoneProjectionRequest.__post_init__`, `TombstoneProjectionMetrics.__post_init__`, and `TombstoneProjectionResult.__post_init__` validate required attributes but never reject extra instance attributes. `object.__new__` plus `object.__setattr__` can add an `extra` field; target/request/result revalidation still succeeds, and a target with extra state can be projected successfully. This violates the exact-field and forbidden-extra-field boundary contract; validate the exact `vars(self)` key set for each model before field use.

## Validation performed

- `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py --basetemp=.codex-workflow/20260805-m9d1/pytest-rereview3-focused` - **23 passed**.
- `$env:PYTHONPATH='src'; python -m pytest -q tests/architecture/test_application_import_boundary.py tests/shared/contracts/foundation/test_schema_validator.py --basetemp=.codex-workflow/20260805-m9d1/pytest-rereview3-arch` - **37 passed**.
- `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/rules/test_tombstone_id_generator.py tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py --basetemp=.codex-workflow/20260805-m9d1/pytest-rereview3-reg` - **32 passed**.
- `$env:PYTHONPATH='src'; python -m pytest -q tests/architecture/test_m9a2_attachment_body_boundary.py tests/architecture/test_m9a3_media_processing_boundary.py tests/architecture/test_m9b_git_boundary.py tests/architecture/test_m8ac_acceptance_boundary.py tests/foundation/integration/test_golden_full_snapshot_export.py --basetemp=.codex-workflow/20260805-m9d1/pytest-rereview3-m9reg` - **17 passed**.
- `$env:PYTHONPATH='src'; python -m compileall -q src tests` - passed.
- `git diff --check` - passed (only existing line-ending warnings).
- Adversarial probes confirmed a custom `__deepcopy__` side effect/`RuntimeError` leak and acceptance of forged extra attributes on target, request, metrics, and result instances.

VERDICT: CHANGES_REQUIRED
