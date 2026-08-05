# M9-B Independent Re-review 12

## Findings

### P1 - Application treats the per-file normalized-byte limit as an aggregate limit

`GitScanBudgets.max_normalized_bytes` is specified as an 8 MiB per-file bound,
and the reader enforces it per observation. `BuildGitCodeDocuments._validate_snapshot`
instead rejects when the sum of all included normalized bytes exceeds that same
per-file value (`build_git_code_documents.py:341-348`). A valid snapshot with
two files each below the configured per-file limit but whose combined size is
above it returns `budget_exceeded`; the application therefore rejects valid
scans and does not implement the documented budget semantics.

### P1 - Forged snapshot excluded-byte counters bypass the aggregate raw budget

The application checks only the sum of included observation bytes against
`max_total_raw_bytes` and never binds `snapshot.metrics.excluded_bytes` into
that budget (`build_git_code_documents.py:341-354`). An exact-class forged
snapshot with valid metric arithmetic (`seen=3`, `included=2`, one generated
exclusion, `excluded_bytes=10000`) and a request whose raw budget is 8192 is
accepted and returns `success`, publishing a plan whose scan metrics exceed the
configured aggregate raw-byte bound. The reader's real path sums all tree-entry
sizes, so this is a dependency-boundary budget bypass.

### P2 - Impossible forged snapshot metrics become `internal_failure` instead of a result-invalid category

`BuildGitCodeDocuments._validate_snapshot` does not rerun
`GitScanMetrics.__post_init__` before dereferencing metric fields. An exact-class
forged metrics object with inconsistent exclusion arithmetic reaches plan
construction, where the new `GitScanMetrics` raises and the outer catch maps it
to `INTERNAL_FAILURE` (`build_git_code_documents.py:127-189`, `306-354`). The
malformed dependency is rejected, but not at the snapshot boundary or with the
stable malformed-result category required by the fix plan.

### P1 - Direct plan/result boundary accepts impossible token counts

`CodeDocumentPlan.__post_init__` only checks that `token_count` is an integer in
`1..1000` (`git_code_source.py:671-673`); it never checks the count against the
chunk text's possible non-overlapping character spans. Replacing a valid chunk's
count with `1000` for a 35-character chunk is accepted, and
`GitCodeBuildResult(status=SUCCESS, plan=...)` also succeeds. This allows a
forged successful result to publish a token count that cannot satisfy the
documented tokenizer-span contract; application-built plans catch it only when
the injected tokenizer is rerun.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review12` -> `35 passed`.
- Independent probes reproduced aggregate normalized-budget rejection, forged excluded-byte budget bypass (`success`), malformed metric mapping to `internal_failure`, and direct acceptance of an impossible `1000` token count for 35-character text.

VERDICT: FAIL
