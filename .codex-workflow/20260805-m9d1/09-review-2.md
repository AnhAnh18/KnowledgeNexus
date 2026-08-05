# M9-D1 Independent Re-review

Review target: current M9-D1 working tree after the changes described in
`07-fix-plan-review.md`, against `02-plan-revised.md` and `AGENTS.md`.

## Findings

- **P1 - Result records do not enforce the deterministic tombstone preimage** — `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:263-275` checks only the `tomb:[0-9a-f]{16}` grammar. A success result accepts a record whose ID is unrelated to `(entity_type, entity_id, reason, dataset_version)` (for example, an all-zero ID), so callers can forge a typed result with an ID that the builder would never generate. Recompute the ID with `TombstoneIdGenerator` and reject mismatches before accepting the record.

- **P1 - Forged metrics bypass nested invariants and can leak `AttributeError`** — `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:202-207` checks the nested object’s exact type but never re-runs `TombstoneProjectionMetrics.__post_init__`. An `object.__new__` metrics instance with `record_count=1`, `root_count=1`, and `child_count=999` is accepted in a successful result; a forged instance missing one of these fields raises `AttributeError` while result construction reads it. Revalidate nested metrics with the sentinel-safe path before dereferencing and preserve only `TypeError`/`ValueError` at this boundary.

- **P1 - Forged targets inside requests are not revalidated and are misclassified** — `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:137-155` verifies only exact dataclass types, then reads target fields without calling `TombstoneTarget.__post_init__`. A forged root with `entity_id='bad id'` is accepted by the request model. `ProjectTombstones.execute` then reaches the builder and returns `schema_validation_failed` (with zero validator calls) instead of the required `invalid_request`; a missing-field forged target makes direct request validation leak `AttributeError` and makes `execute` return `internal_failure`. Revalidate root and every child before field access, and classify all such request failures as `invalid_request`.

- **P1 - Schema-valid null optional fields are rejected at the result boundary** — `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:276-281` requires `detail` and `source_version_last_seen` to be strings whenever their keys are present, but `contracts/foundation/schemas/tombstone_record.schema.json` explicitly permits either string or `null` for both optional properties. A schema-shaped success record carrying `detail: None` or `source_version_last_seen: None` is rejected, contrary to the public schema contract. Accept explicit nulls (while retaining string validation for non-null values).

- **P2 - Builder mutation guard relies on equality instead of canonical bytes/exact key comparison** — `src/knowledgenexus/foundation/domain/rules/tombstone_record_builder.py:55-59` compares the post-validator dictionary to a deep-copied dictionary with `==`. A validator can replace a field with a custom `str` subclass that compares equal to the original; the builder returns the mutated value (`entity_id='evil'`) successfully. The reviewed fix plan requires canonical JSON bytes and the exact expected key set so equal-but-noncanonical/non-JSON-safe mutations fail closed.

## Validation performed

- `python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py` — **19 passed**.
- Adversarial probes reproduced all findings above: mismatched deterministic ID accepted; explicit null optionals rejected; forged metrics with impossible child count accepted; forged target accepted by request and mapped to `schema_validation_failed`; equality-forging validator mutation returned a changed record.
- `$env:PYTHONPATH='src'; python -m pytest -q tests/architecture/test_application_import_boundary.py tests/shared/contracts/foundation/test_schema_validator.py` — **34 passed, 3 errors** during `tmp_path` setup because the host pytest temp root denied `C:\Users\ADMIN\AppData\Local\Temp\pytest-of-ADMIN` access; rerunning with `--basetemp=.codex-workflow/20260805-m9d1/pytest-rereview` produced **37 passed**.
- `$env:PYTHONPATH='src'; python -m compileall -q src tests` — passed.
- `git diff --check` — passed; only existing line-ending warnings were emitted.

VERDICT: CHANGES_REQUIRED
