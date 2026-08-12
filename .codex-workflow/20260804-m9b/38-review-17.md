# M9-B Independent Re-review 17

## Findings

### P1 - `CodeDocumentPlan` accepts forged authority observations via custom equality

`CodeDocumentPlan.__post_init__` does not directly revalidate each entry in
`authority_observations`; it only checks `item != observations_by_path.get(item.path)`
(`src/knowledgenexus/foundation/domain/models/git_code_source.py:618-623`). An
exact-class forged `GitFileObservation` with the correct path and
`symbol_authority=True`, but wrong-runtime-type fields whose `__eq__` returns
`True`, is therefore treated as byte-for-byte identical to the real source
observation. A direct probe replaced the C++ authority observation's
`raw_bytes`, byte sizes, and normalized text with such forged values;
`CodeDocumentPlan(...)` and `GitCodeBuildResult(status=SUCCESS, plan=...)` both
accepted it. This violates the required public-boundary fail-closed behavior
for forged observations and publishes malformed authority provenance.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review17` -> `35 passed`.
- `python -m compileall -q src tests` -> passed.
- Scoped `git diff --check` -> passed (line-ending warnings only).
- Independent probes confirmed exact LF/canonical decimal rejection for both
  Git batch protocols, exact commit/branch identity rejection for whitespace
  variants, successful empty-tree snapshots, and the forged-authority
  acceptance described above.

VERDICT: FAIL
