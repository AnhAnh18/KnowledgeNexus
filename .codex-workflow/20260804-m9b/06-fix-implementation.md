# M9-B Review Fix Implementation

Addressed all confirmed findings from `04-review-1.md`:

- Added deterministic raw/normalized/record/chunk ownership accounting and
  atomic `max_in_memory_bytes` enforcement.
- Hardened tokenizer span checks (`0 <= start < end <= len(text)`, strict
  ordering) and added forged-span coverage.
- Revalidated every repository observation against its raw bytes, normalized
  text, controls, sizes, authority suffix, and aggregate counters before
  building records.
- Strengthened plan/document/chunk field sets, source/ACL/version identity,
  hashes, IDs, line/part metadata, contiguous parts, authority ownership, and
  metrics cross-checks.
- Added Git argv allowlisting, injected-runner output-cap checks, and bounded
  threaded subprocess stream draining; the temporary Git integration test
  confirms dirty worktree edits cannot change pinned blob bytes.
- Moved clone-root directory/final-name/reparse validation into
  `GitSourceConfig`, tightened lowercase OID and C0/C1 path validation, and
  validates use-case dependencies in the constructor.

Focused validation after fixes:

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-fix-final` -> `25 passed`.
- M9-A regression selection -> `47 passed`.
- M8-D/E regression selection -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- scoped `git diff --check` -> passed.
