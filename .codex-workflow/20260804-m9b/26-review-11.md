# M9-B Independent Re-review 11

## Findings

### P1 - Application accepts forged snapshots over configured tree/file budgets

`BuildGitCodeDocuments._validate_snapshot` checks per-file and aggregate byte budgets but never checks `snapshot.metrics.seen <= config.budgets.max_tree_entries` or `len(snapshot.observations) <= config.budgets.max_files`. A forged exact-class snapshot reporting 101 seen entries against a request whose budget allows only 100 tree entries (or carrying 21 observations against a 20-file budget) is accepted, and the use case publishes a successful plan containing the over-budget documents. This bypasses the bounded scan contract at the application dependency boundary (`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:306-346`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:155-178`).

### P2 - Forged incomplete observations still leak as `INTERNAL_FAILURE`

The application validates observation contents by directly dereferencing fields in `_validate_snapshot` rather than rerunning `GitFileObservation.__post_init__` inside a guarded invalid-result boundary. An exact-class observation forged without `raw_bytes` therefore raises `AttributeError` during `execute`; the outer catch maps it to `INTERNAL_FAILURE` instead of rejecting the malformed dependency result as `RESULT_INVALID` (or another stable malformed-result category). This violates the required fail-closed handling of forged observations at the public application boundary (`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:127-142`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:306-338`).

### P1 - Direct plan validation permits fallback chunks to omit trailing source lines

`CodeDocumentPlan.__post_init__` requires the first fallback range to start at line 1 and each later range to advance without a gap, but it never requires the final range to reach the source observation's last line. A forged two-line fallback document with one valid chunk covering only line 1 (with recomputed text, hash, ID, and token count) is accepted as a complete plan, silently dropping the trailing source line. The fallback contract requires complete source-line coverage, not merely a covered prefix (`src/knowledgenexus/foundation/domain/models/git_code_source.py:657-703`).

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review11` -> `35 passed`.
- `python -m compileall -q src tests` -> passed.
- Independent probes reproduced successful over-budget forged snapshots, `internal_failure` for an exact-class observation missing `raw_bytes`, and acceptance of a line-1-only plan for a two-line fallback file.

VERDICT: FAIL
