RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D2 Application-Boundary Coverage Fix - Reviewed

This is a correctly bounded tests-only response to the remaining P2 in
`12-review-final.md`. The missing coverage must be exercised through
`PropagateDelta.execute`, not only through `DeltaPropagationRequest` construction.

## Required test matrix

1. Build independent forged exact-type `DocumentChunkSetSummary` fixtures for
   each of its eight required fields missing and for a forbidden extra field.
   For each fixture, build an exact forged `DeltaPropagationRequest` so the
   constructor cannot reject the fixture before `execute` is reached.

2. Build independent forged nested-entry fixtures for every
   `ChunkStabilityEntry` field missing/extra, malformed `chunk_id`, malformed
   `content_hash`, invalid or inconsistent `part_index`/`part_total`, wrong
   runtime field types (including `content_kind` and `token_count`), and a
   non-entry object in the summary `entries` tuple. Preserve a valid outer
   summary shape except for the targeted mutation so each case identifies the
   boundary guarantee it covers.

3. Parameterize every malformed fixture over both request positions:
   `previous_summaries` and `current_summaries`. Do not reuse mutated frozen
   objects between cases; construct or forge fresh instances so one case
   cannot mask another.

4. For every execute-level case, assert
   `DeltaPropagationStatus.FAILED`,
   `DeltaPropagationFailureCategory.SUMMARY_INVALID`, `records == ()`,
   `count == 0`, `metrics is None`, and no leaked exception or
   `internal_failure`. Inject a counting schema validator and replace the
   use-case projector with a counting test double (or monkeypatch its
   `execute` method); assert both counters remain zero. Keep the existing
   direct-constructor/model tests as lower-level coverage and retain wrong
   request runtime-type tests.

## Scope and verification

Only the focused tests
`tests/foundation/domain/models/test_delta_propagation.py` and
`tests/foundation/application/use_cases/test_propagate_delta.py` may change.
Production code, M8-E/M9-D1 models and semantics, exporters, stores, ledgers,
roadmap/state files, and unrelated tests remain untouched. The tests must
prove validation happens before document maps, diffs, validator calls, or
tombstone projection and that valid/happy-path behavior is unchanged.

Run the focused and bounded suites before the fresh independent review:

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m9d2/pytest-fix3-focused`

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_chunk_stability.py --basetemp=.codex-workflow/20260805-m9d2/pytest-fix3-m9d1-m8e`

`$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m9d2/pytest-fix3-arch`; `python -m compileall -q src tests`; `git diff --check`

Also rerun the prior bounded M9-A/B/C slices recorded in
`08-fix-implementation.md`. Obtain a fresh independent review after all
checks and before any roadmap/state update or commit.
