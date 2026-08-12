# M9-D1 Independent Closeout Review

Review target: current M9-D1 tree after the bounded fixes in
`14-fix3-plan-review.md`, checked against `12-review-3.md` and `AGENTS.md`.
This review did not modify source or tests.

## Findings

- **P1 - Cyclic/malformed builtin containers leak `RecursionError` at the result boundary** - `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:208-213` invokes `_validate_json_object`, whose recursive traversal at lines 255/259 has no cycle/depth guard. A plain builtin record containing a self-referential list or dict (for example, an extra field such as `record["detail"] = cycle`, or any malformed nested value) raises `RecursionError` instead of the required typed `TypeError`/`ValueError`. This violates the adversarial malformed-container/fail-closed contract and lets a non-sanitized exception escape `TombstoneProjectionResult` construction. The traversal must detect cycles (or otherwise bound recursion) and convert malformed nesting to a typed validation error before copying.
- **P1 - Defensive-copy exception boundary is narrower than the reviewed contract** - `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:214-217` catches only `TypeError` and `ValueError` from `copy.deepcopy`, while Fix Plan 3 requires an `Exception` boundary that converts any copy failure to a typed error. A copy failure outside those two classes (for example, a `RuntimeError` from a patched/delegated copy implementation) escapes result construction unchanged. Catch `Exception` and sanitize it to `TypeError`/`ValueError` after the pre-copy validation.

## Validation performed

- `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py --basetemp=.codex-workflow/20260805-m9d1/pytest-review4-focused` - **28 passed**.
- `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/rules/test_tombstone_id_generator.py tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/architecture/test_m9a2_attachment_body_boundary.py tests/architecture/test_m9a3_media_processing_boundary.py tests/architecture/test_m9b_git_boundary.py tests/architecture/test_m8ac_acceptance_boundary.py --basetemp=.codex-workflow/20260805-m9d1/pytest-review4-reg` - **42 passed**.
- `$env:PYTHONPATH='src'; python -m pytest -q tests/architecture/test_application_import_boundary.py tests/shared/contracts/foundation/test_schema_validator.py --basetemp=.codex-workflow/20260805-m9d1/pytest-review4-arch` - **37 passed**.
- `python -m compileall -q src tests` - passed.
- `git diff --check` - passed (only existing LF/CRLF warnings).
- Adversarial probe: a schema-shaped record with a self-referential list or dict reaches `_validate_json_object` and leaks `RecursionError: maximum recursion depth exceeded`.
- Adversarial probe: replacing the module's `copy.deepcopy` with a function that raises `RuntimeError` leaks that runtime exception from result construction.

VERDICT: CHANGES_REQUIRED
