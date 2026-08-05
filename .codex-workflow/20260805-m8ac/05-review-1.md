# M8-AC Independent Review 1

RECOMMENDED_IMPLEMENTATION_PROFILE: build

## Findings

- P1: `MiniCorpusAcceptanceSummary` accepts impossible status/count and ordinal combinations, and distribution tuples without ordered min/median/p95/max invariants.
- P1: Source mutation is not safely represented; a changed fingerprint can raise an unsanitized `ValueError`, and the CLI fingerprint uses only size/mtime rather than content.
- P1: The acceptance summary omits the required tokenizer asset digest and per-pass M8-D/M8-E digests, and does not expose all required distribution/duration observations.
- P1: `no_writes` and `report_leak_free` are hard-coded true rather than observed.
- P1: Aggregate-only model fields allow arbitrary profile/chunker/label strings and duplicate labels.
- P2: Negative probes accept unrelated failure categories and the alternate generation probe uses a hard-coded UUID.
- P2: CLI path checks are lexical only and do not reject symlink/reparse aliases into forbidden paths.
- P2: Selection loading is unbounded before the 10-20 item contract is enforced.
- P2: Focused tests do not cover the required malformed runtime values, impossible counters, content mutation, and symlink cases.

## Verdict

VERDICT: CHANGES_REQUIRED
