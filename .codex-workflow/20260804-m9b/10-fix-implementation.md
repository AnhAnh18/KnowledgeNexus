# M9-B Re-review Fix Implementation

Addressed all findings from `07-review-2.md`:

- `CodeDocumentPlan` now retains immutable included observations for direct
  model-boundary validation, enforces exact document/chunk semantics, hashes,
  source/ACL/version/path identities, authority ownership, ordering, and
  fallback chunk presence.
- Tokenizer offsets now require exact non-boolean integers before comparison.
- `LocalGitRepositoryReader` validates injected runner shape synchronously and
  no longer uses falsey fallback selection.
- Added direct forged-plan, non-integral tokenizer, and malformed-runner tests.

Validation:

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-fix3` -> `28 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_media_materialization.py tests/foundation/application/use_cases/test_fetch_and_store_confluence_attachment_body.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/infrastructure/processors/test_drawio_xml_processor.py tests/foundation/infrastructure/processors/test_media_attachment_processors.py --basetemp=.pytest-m9b-fix3-m9a` -> `47 passed`.
- `python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/application/use_cases/test_build_confluence_chunks.py --basetemp=.pytest-m9b-fix3-m8` -> `70 passed`.
- `python -m compileall -q src tests` -> passed.
- scoped `git diff --check` -> passed.

A fresh independent re-review is required before ledger updates or commit.

## Re-review 2 fixes

- `GitFileObservation` and `CodeDocumentPlan` now revalidate UTF-8 raw bytes,
  canonical normalization, and suffix-derived symbol authority even for
  forged observations.
- Direct plan validation bounds line ranges to the source observation's line
  count.
- `GitScanMetrics` rejects excluded bytes without an excluded-file counter.
- Added direct tests for all three cases.

Latest validation:

- Focused M9-B -> `29 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 16 fix

- Authority observations are now independently revalidated and compared field
  by field, avoiding attacker-controlled dataclass equality.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 15 fix

- Both Git batch protocols now require canonical decimal size headers and exact
  LF terminators; empty trees return empty size maps.
- HEAD/branch identity responses are compared as exact expected bytes with no
  whitespace stripping.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 14 fix

- `cat-file --batch-check` parsing now requires exact LF-terminated decimal
  sizes with no signs/CR/missing terminators.
- Document metadata runtime types are checked before equality comparisons.
- Request construction deeply revalidates config/profile models.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 13 fix

- All injected runner exceptions map to `REPOSITORY_READ_FAILED`.
- `max_file_bytes` is enforced for every blob before generated/vendor/binary
  exclusion handling.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 12 fix

- Guarded missing fields on injected Git command results and revalidated the
  complete snapshot before application identity access.
- Malformed payloads now map to stable sanitized categories.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 9 fix

- Deep nested config/profile validators now run before reader/application use.
- Snapshot observations and successful plans are revalidated at their public
  boundaries.
- Fallback coverage starts at source line 1 and tokenizer span access is
  guarded to return `TOKENIZER_FAILED`.

Latest focused validation: `35 passed`.

## Re-review 11 fix

- Snapshot validation now treats normalized-byte budget as per-file and binds
  aggregate raw budget to included plus excluded bytes.
- Forged metrics are revalidated before application dereference.
- Plan token counts cannot exceed assembled text length.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 10 fix

- Snapshot application validation now enforces tree/file budgets and
  revalidates forged observations before dereference.
- Plan fallback ranges must cover the final source line; overlap is bounded to
  four lines.

Latest focused validation: `35 passed`.

## Re-review 8 fix

- Snapshot/plan boundaries re-run metrics invariants for forged instances.
- Git runner results require exact integer return codes and byte outputs.
- Missing/forged request fields return `INVALID_REQUEST`; reader revalidates
  complete `GitSourceConfig` before nested field access.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 6 fix

- Observation boundaries now reject forbidden C0/C1 controls in raw source
  bytes, including forged instances revalidated by the plan.
- Added direct control-byte adversarial coverage.

Latest focused validation: `34 passed`.

## Re-review 7 fix

- Application execution now requires exact snapshot identity string types and
  exact nested request `GitSourceConfig`/`ChunkingProfile` types before field
  access or dependency calls.
- Added forged snapshot/request boundary tests.

Latest validation:

- Focused M9-B -> `35 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 5 fixes

- Fallback parts now require strictly advancing source-line coverage; empty
  fallback files reject all chunks.
- Plan identity requires exact strings, and snapshot/plan paths reject
  casefold collisions.
- Added direct tests for non-advancing ranges, empty/forged identity cases,
  and casefold collisions.

Latest validation:

- Focused M9-B -> `33 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 4 fixes

- Direct plan validation reconstructs the canonical fallback prefix and source
  line window from the owning observation, rejecting recomputed unrelated body
  text.
- Authority observations must be exactly one sorted, unique entry per path.
- Added forged-body and duplicate-authority adversarial tests.

Latest validation:

- Focused M9-B -> `31 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.

## Re-review 3 fixes

- Direct plan validation now binds authority observations byte-for-byte to the
  included observation, checks included raw/normalized byte totals, bounds
  token counts, and revalidates forged observation paths at snapshot/plan
  boundaries.
- Added direct adversarial coverage for authority substitution, byte-counter
  mismatch, zero token counts, and unsafe paths.

Latest validation:

- Focused M9-B -> `31 passed`.
- M9-A regression -> `47 passed`.
- M8-D/E regression -> `70 passed`.
- Compileall and scoped diff-check -> passed.
