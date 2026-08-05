# M9-A2 Review Fix Plan

## Scope

Address every confirmed finding from `05-review-1.md` without adding network,
parsing, media processing, export, checkpoint, ACL, or downstream storage
behavior.

## Bounded changes

1. Make fetch/store port errors category-only and allowlist store categories;
   sanitize all unexpected fetch/store failures in the use case.
2. Rebuild and validate forged `RawHttpObservation` and
   `MediaBodyStoreBudget` instances before field access or side effects.
3. Serialize cumulative budget accounting across publishes and map scan errors
   to stable categories; retain no-clobber replay semantics.
4. Remove byte-count details from public artifact repr and add adversarial tests
   for forged instances, exception leakage, concurrent budget races, and scan
   failure mapping.

## Validation and re-review

Run the focused M9-A2 suite, M9-A1/schema and raw-store regressions,
compileall, and scoped diff-check; record results in
`07-fix-implementation.md`. Obtain a fresh independent review in
`08-review-2.md`; only `VERDICT: PASS` permits ledger update, commit, and push.
