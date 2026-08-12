# M9-B Independent Re-review 5

## Findings

### P1 - `CodeDocumentPlan` accepts fallback chunks whose text is unrelated to the source observation

The plan boundary validates a chunk's hash, ID preimage, token-count range, and line-number bounds, but never reconstructs the required deterministic prefix plus complete source-line window from the corresponding `GitFileObservation`. Replacing the valid `README.md` fallback text with a different normalized body, then recomputing `content_hash`, `chunk_id`, and `token_count`, is accepted by both `CodeDocumentPlan` and `BuildGitCodeDocuments._validate_plan`. A successful `GitCodeBuildResult` can therefore publish a forged chunk that claims source lines from one document while containing unrelated content, violating the fallback prefix/source-line and provenance contract (`src/knowledgenexus/foundation/domain/models/git_code_source.py:560-625`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:500-613`).

### P2 - `CodeDocumentPlan` does not enforce unique, ordered authority observations

The plan checks only the set of authority paths and field equality with included observations. A tuple containing the same authority observation twice (or in arbitrary order) is accepted, so the public plan can expose duplicate provenance entries despite the exact one-entry-per-authority-file contract (`src/knowledgenexus/foundation/domain/models/git_code_source.py:422-425`, `src/knowledgenexus/foundation/domain/models/git_code_source.py:541-559`).

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review5` -> `31 passed`.
- Direct adversarial probes reproduced acceptance of a recomputed unrelated fallback chunk and duplicate authority observations.

VERDICT: FAIL
