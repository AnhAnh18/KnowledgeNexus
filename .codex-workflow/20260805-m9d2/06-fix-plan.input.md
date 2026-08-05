# M9-D2 Bounded Fix Plan

Address only the P1 in `05-review-1.md`.

- Harden `_validate_summary` to reject forbidden extra/missing fields on the
  outer `DocumentChunkSetSummary` and every nested `ChunkStabilityEntry`.
- Re-run sentinel-safe `__post_init__` on the exact nested entry type before
  any document diff or tombstone projection; forged IDs, hashes, part metadata,
  or nested extras must map to `summary_invalid` atomically.
- Add focused adversarial tests for forged summary extras, missing fields, and
  nested entry hash/extra-field tampering. Do not alter M8-E models or M9-D1
  semantics, exporters, stores, or ledgers.
- Re-run focused M9-D2, M9-D1/M8-D/E/M9-A/B/C regressions, architecture,
  compileall, diff-check, then obtain a fresh independent re-review before any
  roadmap/state update or commit.
