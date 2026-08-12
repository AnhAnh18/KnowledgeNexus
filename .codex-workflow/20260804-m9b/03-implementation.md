# M9-B Implementation Report

## Scope

Implemented the bounded local Git code-document seam from the revised plan.
Source bytes are read from the pinned commit object database through a fixed,
read-only Git runner. The application returns schema-valid Git documents and
fallback `code_window` chunks atomically; C++/Java authority files return
documents and observations but no competing symbol chunks.

## Changed files

- `src/knowledgenexus/foundation/domain/models/git_code_source.py`
- `src/knowledgenexus/foundation/domain/models/__init__.py`
- `src/knowledgenexus/foundation/ports/git_repository_read_port.py`
- `src/knowledgenexus/foundation/ports/__init__.py`
- `src/knowledgenexus/foundation/infrastructure/git/__init__.py`
- `src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py`
- `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py`
- `src/knowledgenexus/foundation/application/use_cases/__init__.py`
- focused M9-B domain, infrastructure, application, and architecture tests.

## Validation commands and results

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-focused-final` -> `21 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-m9a-reg` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-m8-reg` -> `70 passed`.
- `python -m pytest -q tests/foundation --basetemp=.pytest-m9b-foundation` -> `2696 passed, 39 skipped, 45 failed, 9 errors`; failures are the known machine tokenizer-asset/runtime and temp/sidecar/CLI environment failures, with no M9-B test failure in the run.
- `python -m compileall -q src tests` -> passed.
- scoped `git diff --check` -> passed.

## Residual risks before review

- The real M9-B scan has not been run against an operator-approved `spen-sdk`
  clone/commit; only synthetic and temporary local Git fixtures were used.
- The broad Foundation suite remains environment-blocked as recorded above.
- M8-AC real mini-corpus acceptance remains `pending_external_input` and is
  not changed by this stage.
