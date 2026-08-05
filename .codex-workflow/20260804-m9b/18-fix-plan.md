# M9-B Re-review Fix Plan 5

Address only `17-review-6.md`:

- Require exact `str` runtime types for `CodeDocumentPlan.repo_name` and
  `.branch` before identity comparison.
- For each fallback document, require empty normalized sources to have zero
  chunks and non-empty sources to have contiguous parts whose source ranges
  advance (`line_end` strictly increases), preserving ordered non-advancing
  rejection and at least one new source line per window.
- Mirror these checks in the application plan validator and add direct forged
  identity, empty-file chunk, and duplicate-range tests.

Rerun scoped/regression validation and a fresh independent review; no ledger
update until `VERDICT: PASS`.
