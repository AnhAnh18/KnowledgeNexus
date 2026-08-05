# M9-B Independent Re-review 10

## Findings

### P1 - Reader and application do not deeply revalidate forged nested configuration models

`GitSourceConfig.__post_init__` checks only that `budgets` has the exact `GitScanBudgets` class; it does not rerun `GitScanBudgets.__post_init__`. A forged exact-class budget with missing fields therefore passes config revalidation, and `LocalGitRepositoryReader.read` later dereferences `config.budgets.max_tree_entries` after repository I/O and raises a raw `AttributeError` instead of returning a sanitized `INVALID_REQUEST`. The application request boundary similarly checks only the exact outer config/profile classes, so forged nested config/profile instances can reach field access and become `INTERNAL_FAILURE` rather than failing closed as invalid input (`src/knowledgenexus/foundation/domain/models/git_code_source.py:215-219`, `src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:261-272`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:191-227`).

### P1 - Snapshot construction trusts forged observation contents

`GitRepositorySnapshot.__post_init__` verifies observation class, path ordering, and aggregate byte counters, but it never reruns `GitFileObservation.__post_init__` or checks raw UTF-8, normalization, controls, or suffix-derived authority. An exact-class forged observation with `raw_bytes=b"bad!"` and `normalized_text="good"` is accepted by a snapshot with matching lengths and metrics. This publishes an impossible snapshot at the model boundary; the later use-case validator catches only when that snapshot is consumed (`src/knowledgenexus/foundation/domain/models/git_code_source.py:347-370`).

### P1 - Successful build results accept uninitialized forged plans

`GitCodeBuildResult.__post_init__` accepts any exact `CodeDocumentPlan` instance for `status=SUCCESS` without revalidating its invariants. An `object.__new__(CodeDocumentPlan)` instance with no fields can therefore be wrapped in a successful result, violating the typed result/status contract and allowing a success result with no usable plan (`src/knowledgenexus/foundation/domain/models/git_code_source.py:721-729`).

### P1 - Plan range validation allows fallback chunks to omit source lines

`CodeDocumentPlan.__post_init__` checks only that each chunk's `line_end` advances and stays within the source line count. It does not require the first `line_start` to be 1 or subsequent starts to follow the previous covered range (subject to permitted overlap). A forged single chunk covering only line 2 of a two-line file, with matching assembled text, hash, ID, and counters, is accepted as a complete plan, silently dropping line 1 (`src/knowledgenexus/foundation/domain/models/git_code_source.py:654-675`, `src/knowledgenexus/foundation/domain/models/git_code_source.py:685-695`).

### P2 - Forged exact-class tokenizer results with missing fields leak as internal failure

`BuildGitCodeDocuments._validated_token_count` checks only the exact `TokenizationResult` class, then iterates `result.spans` outside a guarded validation block. An exact-class result forged without a `spans` field raises `AttributeError`; `execute` converts this to `INTERNAL_FAILURE` instead of the required stable `TOKENIZER_FAILED` malformed-dependency category (`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:483-508`).

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review10` -> `35 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review10-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review10-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- Independent probes reproduced raw `AttributeError` for a forged nested budget, direct acceptance of a forged snapshot observation, a successful result wrapping an uninitialized plan, acceptance of a line-2-only fallback chunk, and `internal_failure` for a forged tokenizer result without `spans`.

VERDICT: FAIL
