# M9-B Independent Re-review 14

## Findings

### P1 - Unexpected injected runner errors leak their caller-selected category

`LocalGitRepositoryReader._run` catches `GitCodeBuildError` from the injected
runner and re-raises it unchanged (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:394-397`).
The runner contract says unexpected runner exceptions must map to the
sanitized repository-read category. An injected runner that raises
`GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)` therefore
causes `read()` to expose `invalid_request` rather than
`repository_read_failed`, allowing an untrusted dependency to forge the
reader's public failure category.

### P1 - Per-file byte budget is bypassed for excluded files

The reader applies `max_file_bytes` only after generated, vendor, and binary
exclusion checks (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:279-297`).
Consequently, a tree-provided excluded file larger than the configured hard
per-file limit is counted as excluded and the scan still succeeds. A synthetic
reader probe with a 2,000-byte generated blob and `max_file_bytes=1,024`
returned a successful snapshot with `excluded_bytes=2000`, violating the
contract that any per-file budget breach fails atomically.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review14` -> `35 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review14-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review14-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` -> passed (line-ending warnings only).
- Independent probes reproduced the leaked `invalid_request` runner category and successful acceptance of an excluded 2,000-byte file over a 1,024-byte per-file budget.

VERDICT: FAIL
