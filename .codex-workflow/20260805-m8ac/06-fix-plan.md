# M8-AC Review Fix Plan

## Scope

Address every confirmed P1/P2 finding from `05-review-1.md` without changing
M8-D/E processing semantics or adding raw-data output.

## Bounded changes

1. Tighten the aggregate summary boundary: exact active profile/chunker and
   tokenizer-asset digest, canonical per-pass digests, allowlisted observation
   labels, ordered distributions, and status/ordinal/counter invariants.
2. Make the acceptance runner fail closed on source mutation, use content
   fingerprints, report observed no-write/leak gates, and require exact
   negative-probe categories including an injected generation mismatch.
3. Harden CLI input paths against existing symlink/reparse aliases and bound
   selection-file size before JSON parsing.
4. Add adversarial tests for malformed values, counters/distributions,
   mutation, probe categories, symlink paths, and canonical digest fields.

## Validation and review

Run the focused M8-AC suite, M8-D/E and normalizer regressions, architecture,
compileall, and diff-check. Record results in `07-fix-implementation.md`.
Then obtain a fresh independent re-review in `08-review-2.md`; only a PASS
permits ledger update and commit.
