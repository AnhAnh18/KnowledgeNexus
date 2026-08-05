RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-C Final Plan Review

The final plan incorporates the requested legacy compatibility, generic stream
invariants, report sections, validator ordering, mutation detection, and
cleanup/no-clobber requirements. One boundary remains underspecified before
approval.

## Required Correction

- Make the shared `FoundationSchemaValidator` concrete and authoritative for
  generic mode, as in the closed M10-B boundary. “Require a callable shared
  validator” must not permit a no-op/protocol fake to bypass manifest or JSONL
  schema validation. Reject wrong types/subclasses or otherwise construct the
  canonical shared validator before filesystem inspection, and sanitize
  construction/validation exceptions without adapter or report side effects.

Also enumerate the fixed metric-section key sets and source-scope value schema
used by `M10QualityReportInput`; generic scalar filtering alone cannot reliably
prevent IDs, URLs, paths, principals, hashes, or exception text from entering
the deterministic report.

## Confirmed Coverage

- Legacy `one_page_quality` behavior and golden bytes are explicitly preserved;
  generic mode is additive and mutually exclusive.
- Strict duplicate-key/non-finite readback, exact counts, source-scope equality,
  non-empty media/symbol/sync acceptance, empty tombstones, and quality-input
  mutation checks are specified.
- The exact twelve report sections/order, publication markers, pure rendering,
  no-clobber cleanup, unchanged machine streams, no `LATEST.txt`, and bounded
  M6G/architecture/compileall/diff-check gates are included.

VERDICT: CHANGES_REQUIRED
