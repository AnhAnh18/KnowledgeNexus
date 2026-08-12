RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D2 Bounded Fix Plan - Reviewed

The input plan is correctly scoped to the single confirmed P1 and is
buildable as a localized validation fix. The implementation must make the
validation order and boundary mapping explicit so forged nested M8-E state
cannot be dereferenced or projected.

## Required implementation details

1. In `delta_propagation.py`, define the exact field sets for
   `DocumentChunkSetSummary` (all eight dataclass fields) and
   `ChunkStabilityEntry` (all six fields). In `_validate_summary`, first
   require the exact outer type, then compare its runtime attributes with the
   outer set. Before calling either model `__post_init__`, iterate the outer
   `entries` container only after safely obtaining it; require every entry to
   be the exact `ChunkStabilityEntry` type and to have exactly the nested field
   set. Re-run `ChunkStabilityEntry.__post_init__` for each entry, then
   `DocumentChunkSetSummary.__post_init__`. Missing attributes, extra
   attributes, forged IDs/hashes/part metadata, and any other validation
   exception must be converted to `_SummaryValidationError` (there must be no
   leaked `AttributeError`). Do not modify the M8-E model definitions.

2. Keep this validation before building document maps, calculating diffs, or
   calling `ProjectTombstones`. `DeltaPropagationRequest.__post_init__` must
   reject invalid summaries, while `PropagateDelta.execute` must map a
   revalidation failure on an exact but forged request to
   `DeltaPropagationFailureCategory.SUMMARY_INVALID`, with a failed result
   containing no records, count, or metrics. The validator and projector must
   not be called on this path; valid summaries and all existing M9-D2/M9-D1
   behavior remain unchanged.

## Required adversarial tests

- Forge an outer summary with an extra field and with each required field
  missing; assert construction/request validation fails closed.
- Forge an exact nested entry with an extra field, a missing field, a bad
  `chunk_id`, forged `content_hash`, invalid `part_index`/`part_total`, and
  wrong field types. Put it in a forged exact-type request (using
  `object.__new__`/`object.__setattr__`) and assert `execute` returns
  `SUMMARY_INVALID`, `records == ()`, `count == 0`, and `metrics is None`.
- Exercise both `previous_summaries` and `current_summaries`, and assert a
  counting schema validator receives zero calls for every malformed-summary
  case. Retain the existing `object()`, `None`, wrong-container, and happy
  path tests.

## Scope and acceptance

Only the M9-D2 summary-validation helper and focused M9-D2 model/use-case
tests should change. Do not alter M8-E models, M9-D1 semantics, exporters,
stores, ledgers, or roadmap/state artifacts. Acceptance requires all malformed
summary cases to fail atomically as `summary_invalid`, valid summaries to
produce the prior deterministic results, and no side effect before complete
validation.

Run the focused suite and bounded regressions with exact commands, followed by
architecture, compile, and diff checks:

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m9d2/pytest-fix-focused`

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_chunk_stability.py --basetemp=.codex-workflow/20260805-m9d2/pytest-fix-m9d1-m8e`

`$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m9d2/pytest-fix-arch`; `python -m compileall -q src tests`; `git diff --check`

Obtain a fresh independent re-review after these checks and before any
roadmap/state update or commit.
