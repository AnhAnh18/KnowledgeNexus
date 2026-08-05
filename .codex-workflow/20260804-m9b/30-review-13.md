# M9-B Independent Re-review 13

## Findings

### P1 - Reader leaks `AttributeError` for forged exact-class command results

`LocalGitRepositoryReader._run` verifies `type(result) is GitCommandResult` and then directly dereferences `result.returncode`, `result.stdout`, and `result.stderr` (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:398-405`). An injected runner can return an exact-class forged result created with `object.__new__(GitCommandResult)` but missing `stdout`/`stderr`; `read()` then raises a raw `AttributeError` instead of mapping the malformed dependency result to the sanitized `repository_read_failed` category. This violates the public runner boundary's fail-closed malformed-result contract and can expose an unexpected exception to direct callers.

### P1 - Application leaks malformed snapshots with missing required top-level fields as `internal_failure`

`BuildGitCodeDocuments.execute` checks the snapshot class and immediately dereferences `snapshot.repo_name`, `snapshot.branch`, and `snapshot.commit_sha` before entering the guarded snapshot validation (`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:131-142`). An exact-class forged `GitRepositorySnapshot` missing any of those fields (or missing `observations`) therefore raises `AttributeError`, which the outer catch converts to `internal_failure`; it is not rejected as the malformed dependency result category `result_invalid`. The required adversarial public-boundary behavior is to fail closed before field access with a stable result-invalid category and no partial output.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review13` -> `35 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review13-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review13-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` -> passed (line-ending warnings only).
- Independent probes reproduced raw `AttributeError` for a forged exact-class `GitCommandResult` missing `stdout`, and `internal_failure` for forged exact-class snapshots missing `repo_name`, `branch`, `commit_sha`, or `observations`.

VERDICT: FAIL
