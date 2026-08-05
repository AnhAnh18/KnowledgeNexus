# M9-B Independent Re-review 6

## Findings

### P1 - `CodeDocumentPlan` accepts fallback windows that do not advance through source lines

The model reconstructs each chunk's text from its declared source range, but it only checks each range independently and that `part_index` values are contiguous. It never requires sorted source ranges, strictly increasing coverage, or at least one new source line per part. A forged second chunk can therefore reuse the first chunk's exact text and `line_start`/`line_end` (with a recomputed hash and ID) and is accepted by `CodeDocumentPlan`; the application validator has the same gap. This publishes duplicate/incorrect line provenance despite the fallback contract requiring windows ordered by source position with at least one new source line (`src/knowledgenexus/foundation/domain/models/git_code_source.py:629-660`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:627-648`).

### P1 - Empty fallback documents can carry fabricated chunks

The fallback contract requires an empty normalized file to produce zero chunks. Both validators only reject missing chunks for non-empty fallback documents and never reject a non-empty chunk group when `normalized_byte_size == 0`. A direct caller can construct an empty `README.md` observation/document and add the exact prefix-only chunk for source line `1/1`, then publish a successful `GitCodeBuildResult` with fabricated content for an empty source (`src/knowledgenexus/foundation/domain/models/git_code_source.py:651-660`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:627-647`).

### P2 - `CodeDocumentPlan` accepts non-string plan identity values via forged equality

The plan boundary compares `repo_name` and `branch` to literals without first requiring exact `str` runtime types. An object whose `__eq__` returns `True` for `"spen-sdk"`/`"develop"` is accepted, and `GitCodeBuildResult(status=SUCCESS, plan=...)` then accepts the malformed plan. This violates the required wrong-runtime-type fail-closed boundary and leaves downstream serialization/identity consumers with non-string fields (`src/knowledgenexus/foundation/domain/models/git_code_source.py:405-406`).

### P1 - Forged snapshots and plans allow casefold-colliding paths

The snapshot and plan validators require exact path sorting/uniqueness but never reject casefold-equivalent paths, even though `REJECT_CASEFOLD_COLLISIONS` is the only supported policy. A direct snapshot with both `A.py` and `a.py` is accepted and `BuildGitCodeDocuments` returns success with both documents and fallback chunks. This bypasses the reader's casefold collision check and can create ambiguous identities for case-insensitive consumers (`src/knowledgenexus/foundation/domain/models/git_code_source.py:349-355`, `src/knowledgenexus/foundation/domain/models/git_code_source.py:434-437`, `src/knowledgenexus/foundation/application/use_cases/build_git_code_documents.py:294-299`).

### P1 - Direct observation/plan boundaries accept forbidden source controls

`GitFileObservation` and `CodeDocumentPlan` revalidate UTF-8 and normalization but never reject NUL or unsupported C0/C1 controls in raw/normalized source text. A direct authority observation containing `b"bad" + bytes([0x01])` is accepted, and a matching document, authority tuple, and empty chunk set form a successful `CodeDocumentPlan`, although the reader/application contract must reject such text (`src/knowledgenexus/foundation/domain/models/git_code_source.py:246-276`, `src/knowledgenexus/foundation/domain/models/git_code_source.py:411-434`).

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review6` -> `31 passed`.
- Independent probes reproduced acceptance of duplicate/non-advancing line ranges, an empty-file chunk, and forged non-string plan identity.
- An independent forged-snapshot probe reproduced acceptance of `A.py` plus `a.py` and a successful build result.
- A direct observation/plan probe reproduced acceptance of a C0 control byte (`bytes([0x01])`) in source content.

VERDICT: FAIL
