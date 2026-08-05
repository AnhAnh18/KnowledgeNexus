# M9-B Independent Re-review 4

Scope: second-fix implementation (`10-fix-implementation.md`), second-fix plan,
M9-B production and focused tests only. No production or test files were edited.

## Findings

### P1 - `CodeDocumentPlan` accepts forged authority observations

The plan validates only the path/set relationship for
`authority_observations`; it does not require each authority observation to be
the same validated observation (or to have matching bytes, normalized text, and
sizes) as the corresponding item in `observations`. A direct caller can replace
the `src/main.cpp` authority observation with a valid observation containing
different source bytes and construct a successful `CodeDocumentPlan` and
`GitCodeBuildResult`. This lets downstream M9-C consumers receive provenance
bytes that do not belong to the plan's document. The gap is in
`src/knowledgenexus/foundation/domain/models/git_code_source.py:416-543`.

### P1 - `CodeDocumentPlan` accepts metrics whose byte counters disagree with its contents

The plan cross-checks only included-document and included-chunk counts. It does
not cross-check `metrics.included_raw_bytes` or
`metrics.included_normalized_bytes` against `observations`, nor otherwise bind
the metric counters to the plan contents. Replacing `included_raw_bytes` with
the correct value plus one is accepted and can be wrapped in a successful
`GitCodeBuildResult`, violating the required all-metrics-equal-plan contract.
The affected checks are `src/knowledgenexus/foundation/domain/models/git_code_source.py:490-529` and
`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:500-504`.

### P1 - `CodeDocumentPlan` accepts forged chunk token counts

The direct plan validator verifies chunk text, content hash, identity, and
line/part metadata but never validates `token_count` as an exact concrete
non-negative integer equal to the tokenizer result (or enforces the hard
maximum). A valid chunk with `token_count=0` is accepted and can be published
in a successful result. The use-case validator catches this only for plans it
builds itself; the public plan/result boundary remains forgeable at
`src/knowledgenexus/foundation/domain/models/git_code_source.py:544-613`.

### P1 - Forged observation paths are not revalidated at the snapshot/plan application boundary

`GitRepositorySnapshot` and the application snapshot validator do not re-run
the safe Git path policy for forged `GitFileObservation` instances. A
`GitFileObservation` forged with `path="../evil.md"` (while keeping otherwise
consistent UTF-8 and size fields) is accepted by the snapshot and the use case
returns `success` with a document and fallback chunk using that unsafe path.
This bypasses the required POSIX-relative/no-dot-component boundary and is
visible in `src/knowledgenexus/foundation/domain/models/git_code_source.py:326-351` and
`src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:291-323`.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review4` -> `29 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-review4-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-review4-m8` -> `70 passed`.
- Direct probes reproduced all four findings: forged authority bytes, byte-counter mismatch, zero token count, and `../evil.md` path each reached an accepted plan/success result.

VERDICT: FAIL
