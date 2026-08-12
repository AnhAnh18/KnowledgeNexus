# M8-AC Review Fix Implementation

Implemented the bounded fixes from `06-fix-plan.md`.

## Changes

- Aggregate summary now enforces exact active profile/chunker identity,
  tokenizer-asset digest, per-pass page-set/stability digests, ordered
  distributions, fixed observation labels, status/ordinal/counter coherence,
  and known content kinds.
- The runner hashes source bytes, fails closed with `mutation_detected`,
  observes an explicit whole-root write fingerprint, verifies the serialized
  report allowlist, and checks exact negative-probe categories including an
  injected wrong-generation envelope.
- CLI input is bounded before JSON parsing and rejects lexical/resolved
  forbidden paths plus existing symlink/junction/reparse aliases; missing
  roots/files fail as sanitized configuration input.
- Distribution labels and pending-external-input summaries are cross-checked
  against counters, distributions, digests, and gate booleans.
- Added malformed-input, counter/distribution, mutation, size-bound, and
  symlink tests.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_confluence_mini_corpus_acceptance.py tests/foundation/application/use_cases/test_accept_confluence_mini_corpus.py tests/foundation/cli/test_accept_confluence_mini_corpus_cli.py tests/architecture/test_m8ac_acceptance_boundary.py --basetemp=.pytest-m8ac-fix8` -> `15 passed, 1 skipped`.
- M8-D/E, page-set, normalizer, parser, and chunking regression selection -> `164 passed, 1 failed`; the sole failure is the pre-existing `test_invalid_canonical_document_fails_schema_validation_without_details` in `test_build_confluence_chunks.py`, unrelated to M8-AC changes.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` on the bounded M8-AC scope -> passed.

Real mini-corpus execution remains `pending_external_input`; no raw or
runtime artifacts were added.
