# M9-D1 Implementation Report

Implemented the reviewed M9-D1 tombstone contract and explicit document
cascade without wiring exporters, stores, checkpoints, clocks, or network I/O.

## Changes

- Added runtime-validated tombstone target/request/result models with immutable
  metadata, canonical timestamps, entity-ID grammars, duplicate policy, JSON
  safety, and cross-field metric/status invariants.
- Added schema-valid deterministic `TombstoneRecordBuilder` and additive
  Foundation exports.
- Added atomic `ProjectTombstones` application use case with fixed ordering,
  canonical JSON collision comparison, sanitized failure categories, and no
  partial records.
- Added focused adversarial model, builder, and use-case tests.

## Validation

- `python -m pytest -q --basetemp=.pytest-m9d1-focused3 tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py` - 14 passed.
- `python -m pytest -q --basetemp=.pytest-m9d1-reg tests/foundation/domain/rules/test_tombstone_id_generator.py tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py` - 32 passed.
- `python -m pytest -q --basetemp=.pytest-m9d1-arch tests/architecture` - 86 passed.
- `python -m compileall -q src tests` - passed.
- `git diff --check` - passed (only existing line-ending normalization warnings).
