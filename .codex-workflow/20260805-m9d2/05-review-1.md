# M9-D2 Independent Review 1

Review target: current uncommitted M9-D2 implementation against
`.codex-workflow/20260805-m9d2/02-plan-revised.md`,
`.codex-workflow/20260805-m9d2/03-implementation.md`, `AGENTS.md`, and the
approved M8-E/M9-D1 contracts. This was a fresh independent review. Source and
test files were not modified.

## Findings

- **P1 - Forged M8-E summaries are accepted at the M9-D2 boundary** -
  `src/knowledgenexus/foundation/domain/models/delta_propagation.py:68-76`
  only checks the exact outer `DocumentChunkSetSummary` type and invokes its
  `__post_init__`. It does not reject extra instance fields and does not invoke
  `ChunkStabilityEntry.__post_init__` for nested entries. An adversarial frozen
  summary with `object.__setattr__(summary, "extra", 123)` is accepted by
  `DeltaPropagationRequest` and produces a successful delta. Likewise, a
  nested `ChunkStabilityEntry` whose `content_hash` is forged to `"bad"` is
  accepted and produces a successful result. A forged nested chunk ID reaches
  tombstone construction and is instead reported as `internal_failure`, not
  the required sanitized `summary_invalid`. This violates the revised plan's
  requirement to revalidate exact immutable M8-E state and AGENTS.md's
  fail-closed adversarial boundary rule; malformed IDs/hashes or forbidden
  fields can therefore influence propagation or leak the wrong failure
  category instead of being rejected atomically. Revalidate exact summary
  fields and every nested entry (including exact entry fields) before any diff
  or tombstone side effect.

## Validation

- Focused M9-D2 tests:
  `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m9d2/pytest-review-1-focused`
  -> **20 passed**.
- M9-D1 model/builder/use-case regressions:
  `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py --basetemp=.codex-workflow/20260805-m9d2/pytest-review-1-m9d1`
  -> **31 passed**.
- M8-E model regression:
  `$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_chunk_stability.py --basetemp=.codex-workflow/20260805-m9d2/pytest-review-1-m8e`
  -> **23 passed**.
- M8-D/E and M9-A/B/C bounded regression slice (chunking, media, attachment,
  Git, symbols, relations): **147 passed**.
- Architecture suite:
  `$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m9d2/pytest-review-1-arch`
  -> **87 passed**.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` -> passed (only existing LF/CRLF normalization warnings).
- Adversarial probes for `None`, `object()`, list, and dict requests failed
  closed as `invalid_request`; forged summary extra-field and forged nested
  entry-hash probes reproduced the P1 finding, while a forged nested chunk ID
  returned `internal_failure` instead of `summary_invalid`.

VERDICT: CHANGES_REQUIRED
