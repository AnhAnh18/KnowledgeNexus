# M9-B Re-review Fix Plan 2

Address only findings in `11-review-3.md`:

1. Strengthen `GitFileObservation` and `CodeDocumentPlan` provenance checks.
   - Strictly decode `raw_bytes` as UTF-8 and require the supplied normalized
     text to equal `TextNormalizationRules.normalize_text(decoded raw bytes)`.
   - Require `symbol_authority` to equal the fixed C++/Java authority suffix
     policy, so a caller cannot promote README or other fallback files.
   - Keep document hash/size/metadata checks based on these validated
     observations.
2. Bound fallback chunk line ranges to the owning observation's one-based
   source line count; reject impossible ranges at direct model construction.
3. Reject `GitScanMetrics.excluded_bytes > 0` when all exclusion counters are
   zero, preserving typed cross-field consistency.

Add direct adversarial tests for raw/normalized mismatch, wrong authority
suffix, impossible line ranges, and inconsistent excluded-byte counters. Run
the focused and M9-A/M8-D/E regressions, compileall, diff-check, then launch a
new independent review. Do not update ledgers until `VERDICT: PASS`.
