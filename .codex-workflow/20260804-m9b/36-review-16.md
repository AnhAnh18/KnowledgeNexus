# M9-B Independent Re-review 16

## Findings

### P1 - `cat-file --batch` parser accepts malformed size fields

`LocalGitRepositoryReader._read_blobs` parses the batch header with `int(size_text)` (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:488-499`). This accepts non-exact size fields such as `+5`, `5\r`, and `05` when the expected size is 5. A direct injected-runner probe returned a successful blob for both `+5` and `5\r`; the contract requires exact Git headers and malformed dependency payloads must fail closed, just as the repaired `--batch-check` parser now does.

### P1 - Commit/branch identity parser accepts non-exact command output

`_verify_identity` decodes command output and applies `.strip()` before comparison (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:412-421`). Consequently, forged outputs with extra spaces, CRLF, leading newlines, or extra trailing newlines are accepted as the pinned commit/branch. Direct probes accepted `commit_sha + b" \\n"` with `b"develop\\r\\n"`, and `b"\\n" + commit_sha + b"\\n"` with `b"develop\\n\\n"`. The identity contract requires the exact commit and branch records, so malformed dependency output must be rejected before tree/blob processing.

### P2 - Empty pinned trees fail instead of producing an empty snapshot

`read` always invokes `_read_blob_sizes` after `ls-tree`; when the pinned tree has no entries, the valid empty response is `b""`, but `_read_blob_sizes` requires `stdout.endswith(b"\\n")` and raises `BLOB_READ_FAILED` (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:454-465`). A direct empty-tree runner probe reproduced `blob_read_failed`. The domain snapshot and plan models permit zero observations, and the scan contract permits empty files/documents, so an empty commit tree should return a successful zero-document snapshot rather than fail as malformed.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review16` -> `35 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review16-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review16-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- Independent malformed-payload probes reproduced all three findings.

VERDICT: FAIL
