# M9-B Independent Re-review 9

## Findings

### P1 - Snapshot and plan boundaries trust forged `GitScanMetrics` instances

`GitRepositorySnapshot` and `CodeDocumentPlan` require only the exact
`GitScanMetrics` class and cross-check included/document/chunk byte totals. They
do not revalidate `seen`, exclusion counters, or excluded-byte consistency.
An `object.__new__(GitScanMetrics)` instance with `seen=999`,
`excluded_generated=999`, and `excluded_bytes=999` is accepted by a snapshot;
the same forged counters are accepted by a plan and can be wrapped in a
successful `GitCodeBuildResult`. This violates the required impossible-counter
fail-closed boundary and the contract that all metrics cross-check the plan
contents (`src/knowledgenexus/foundation/domain/models/git_code_source.py:353-364`,
`src/knowledgenexus/foundation/domain/models/git_code_source.py:469-470`,
`src/knowledgenexus/foundation/domain/models/git_code_source.py:543-548`).

### P1 - Injected runner can forge a successful malformed `GitCommandResult`

`LocalGitRepositoryReader._run` checks only `type(result) is GitCommandResult`,
then compares `result.returncode != 0` without revalidating field runtime types.
A forged exact-class result with `returncode=False` (and otherwise valid bytes)
is therefore treated as a zero exit code; the reader returns a successful
snapshot from the malformed dependency result. This violates the runner seam's
exact result contract and accepts a wrong-runtime-type result at a public
boundary (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:378-399`).

### P2 - Missing fields on a forged build request are reported as internal failure

`BuildGitCodeDocuments._validate_dependencies` accesses `request.config` and
`request.chunking_profile` immediately after checking only the outer request
class. A forged `BuildGitCodeDocumentsRequest` created without either field
returns `INTERNAL_FAILURE` rather than rejecting the malformed request as
`INVALID_REQUEST` before field access. The same boundary therefore does not
meet the required missing-field fail-closed behavior
(`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:191-222`).

### P2 - Reader exposes raw exceptions for forged incomplete source configs

`LocalGitRepositoryReader.read` checks only the exact `GitSourceConfig` class,
then dereferences nested fields without revalidating the forged instance. A
`GitSourceConfig` allocated without `budgets` raises an unsanitized
`AttributeError` from `read` instead of a stable `GitCodeBuildError` category,
violating the malformed-input boundary contract (`src/knowledgenexus/foundation/infrastructure/git/local_git_repository_reader.py:261-300`).

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review9` -> `35 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review9-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review9-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- Independent probes reproduced forged metrics accepted by snapshot/plan/result, a forged `returncode=False` runner result producing a successful snapshot, a missing-field request returning `internal_failure`, and an incomplete config raising raw `AttributeError`.

VERDICT: FAIL
