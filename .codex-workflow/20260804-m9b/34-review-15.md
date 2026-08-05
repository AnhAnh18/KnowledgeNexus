# M9-B Independent Re-review 15

## Findings

### P1 - Git batch payload parser accepts non-exact size records

`LocalGitRepositoryReader._read_blob_sizes` uses `splitlines()` and `int(size_text)` for the injected `cat-file --batch-check` response (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:461-473`). This accepts malformed records such as `oid blob +5\n`, `oid blob 5\r`, and even `oid blob 5` without the required terminating LF; the reader then proceeds to a successful snapshot. The contract requires exact Git headers/byte counts and malformed dependency payloads must fail closed, so an untrusted runner can forge blob sizes and bypass the parser's boundary checks.

### P1 - `CodeDocumentPlan` accepts boolean document metadata in integer fields

The plan compares `document["metadata"]` to the expected mapping with normal Python equality but never validates exact runtime types for `raw_byte_size`, `normalized_byte_size`, or `symbol_authority` (`src/knowledgenexus/foundation/domain/models/git_code_source.py:515-536`). Because `False == 0` and `True == 1`, a forged document with boolean metadata is accepted as a valid plan. An adversarial probe built a zero-byte observation, replaced both byte-size metadata values with `False`, and `CodeDocumentPlan(...)` returned successfully. This violates the required typed model boundary and permits impossible metadata into a successful result.

### P2 - `BuildGitCodeDocumentsRequest` constructor accepts forged nested values

`BuildGitCodeDocumentsRequest.__post_init__` checks only that `config` and `chunking_profile` have the exact classes; it does not revalidate their fields (`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:90-95`). Exact-class instances created with `object.__new__(GitSourceConfig)` or `object.__new__(ChunkingProfile)` are accepted by the public constructor. `execute` later rejects them, but the constructor itself violates the required public-boundary fail-closed contract for missing/forged required fields.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review15` -> `35 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review15-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review15-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- Scoped `git diff --check` -> passed.
- Independent probes reproduced successful acceptance of malformed batch-check size records, boolean plan metadata, and forged nested request values.

VERDICT: FAIL
