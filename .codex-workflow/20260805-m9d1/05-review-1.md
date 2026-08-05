# M9-D1 Independent Review

Review target: current uncommitted M9-D1 implementation against `02-plan-revised.md` and `AGENTS.md`.

## Findings

- **P1 - Validator mutation can produce a successful malformed record** — `src/knowledgenexus/foundation/application/use_cases/project_tombstones.py:60-90` trusts the dictionary after `TombstoneRecordBuilder.build()` and only checks that `tombstone_id` is a string. A dependency validator that removes `entity_id` (or otherwise mutates a record) returns `SUCCESS` with a record that is not `TombstoneRecord`-shaped. The revised plan explicitly requires mutated/partial validator output to fail atomically; revalidate the returned record (or validate an immutable copy) before appending it.

- **P1 - Public success results accept non-schema records** — `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:164-187` checks only JSON safety and count arithmetic. It accepts `TombstoneProjectionResult(status=SUCCESS, records=({'foo': 1},), count=1, metrics=TombstoneProjectionMetrics(1, 1, 0))`, despite the contract requiring schema-shaped tombstone dictionaries. This allows callers to forge a typed success result that downstream code may trust; enforce the exact TombstoneRecord key/field contract (including optional-field rules) at this boundary.

- **P1 - Forged frozen targets are not revalidated by the request model** — `src/knowledgenexus/foundation/domain/models/tombstone_propagation.py:121-138` verifies only that `root`/children have the exact dataclass type, then reads their fields without invoking `TombstoneTarget.__post_init__`. A forged `TombstoneTarget` created with `object.__new__` and `entity_id='bad id'` is accepted by `TombstoneProjectionRequest`, so the supposedly runtime-validated request can contain invalid IDs. An uninitialized forged target instead raises `AttributeError` during request/build construction, violating the required TypeError/ValueError fail-closed boundary. Revalidate root and every child before field access; the use case should classify such requests as invalid rather than `internal_failure`.

- **P1 - Default construction performs filesystem I/O in a pure seam** — `src/knowledgenexus/foundation/application/use_cases/project_tombstones.py:33-35` constructs `FoundationSchemaValidator()` when no dependency is supplied. That constructor loads every contract schema from disk, so `ProjectTombstones()` performs filesystem reads before `execute`; a guard replacing `Path.read_text` with an exception fails at construction. The revised plan forbids filesystem calls for this pure projection seam. Require an already-created validator/dependency, or otherwise move schema loading outside the pure boundary.

## Validation performed

- `python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py` — 14 passed.
- `python -m pytest -q tests/architecture/test_application_import_boundary.py tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py tests/shared/contracts/foundation/test_schema_validator.py` — 48 passed; 3 schema-validator tests could not set up `tmp_path` because the host pytest temp root returned `PermissionError`.
- `python -m compileall -q` on the three M9-D1 modules — passed.
- `git diff --check` — passed (only line-ending warnings on existing modified export files).
- Manual adversarial probes reproduced the malformed-success validator case, arbitrary success records, forged-target acceptance/`AttributeError`, and default-constructor filesystem access described above.

VERDICT: CHANGES_REQUIRED
