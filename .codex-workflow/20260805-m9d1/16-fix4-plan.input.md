# M9-D1 Fix Plan 4

Address only the closeout finding in `15-review-4.md`.

- Add cycle detection to recursive JSON-safe validation for builtin dict/list/
  tuple containers, using an active-object identity set and typed
  `TypeError`/`ValueError` rejection rather than recursion leakage.
- Convert any unexpected defensive-copy exception after validation into the
  same typed result-boundary rejection; no arbitrary exception may leak.
- Add a focused adversarial cyclic-container test.
- Preserve all schema-shape, defensive-copy, purity, and result invariants;
  rerun focused/regression/architecture, compileall, diff-check, and a fresh
  independent closeout review.
