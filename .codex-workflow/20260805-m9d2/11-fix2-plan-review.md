RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D2 Test-Coverage Fix Plan - Reviewed

The input plan is an appropriately bounded, tests-only response to the P2
finding. It should be implemented with the following exact matrix so the
already-correct production fix remains protected at both construction and
application boundaries.

## Required test design

1. Parameterize all eight `DocumentChunkSetSummary` fields for both a missing
   attribute and a forbidden extra attribute. Build forged exact-type
   summaries with `object.__new__`/`object.__setattr__`; assert direct request
   validation fails only with `TypeError`/`ValueError` and does not leak
   `AttributeError`.

2. Parameterize nested `ChunkStabilityEntry` cases for each missing/extra
   field, malformed `chunk_id`, malformed `content_hash`, invalid or
   inconsistent `part_index`/`part_total`, wrong field runtime types, and a
   non-`ChunkStabilityEntry` object in `entries`. Use a forged exact summary
   and forged exact `DeltaPropagationRequest` so the application boundary is
   exercised without the constructor repairing or rejecting the fixture.

3. Run every malformed-summary case in both `previous_summaries` and
   `current_summaries`. Assert `PropagateDelta.execute` returns
   `DeltaPropagationStatus.FAILED` with
   `DeltaPropagationFailureCategory.SUMMARY_INVALID`, `records == ()`,
   `count == 0`, and `metrics is None`; assert no `internal_failure` or raw
   exception is exposed.

4. Prove validation precedes all dependencies for every case: inject a
   counting schema validator and replace the use case's projector with a
   counting test double/monkeypatch. Assert both call counts remain zero when
   the malformed summary is encountered, including current-summary cases.
   Keep existing happy-path and wrong request runtime-type tests intact.

## Scope and acceptance

Only focused tests under
`tests/foundation/domain/models/test_delta_propagation.py` and
`tests/foundation/application/use_cases/test_propagate_delta.py` should
change. Do not modify production code, M8-E/M9-D1 models or semantics,
exporters, stores, ledgers, or roadmap/state artifacts. Test helpers may forge
frozen instances solely to exercise runtime revalidation; they must not weaken
normal constructors or alter shared fixtures.

Acceptance requires the complete outer/nested matrix, both summary tuple
positions, atomic `summary_invalid` results, and zero validator/projector
calls. Run:

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m9d2/pytest-fix2-focused`

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_chunk_stability.py --basetemp=.codex-workflow/20260805-m9d2/pytest-fix2-m9d1-m8e`

`$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m9d2/pytest-fix2-arch`; `python -m compileall -q src tests`; `git diff --check`

Obtain a fresh independent final review after these checks and before any
roadmap/state update or commit.
