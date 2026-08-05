# M9-D1 Fix Plan 3

Address only the two findings in `12-review-3.md`.

1. Validate result records for exact JSON-safe/tombstone shape before any
   `deepcopy`, then perform a defensive copy inside a typed exception boundary
   so custom copy hooks cannot cause side effects or leak arbitrary exceptions.
2. Reject forbidden extra instance attributes in every tombstone model by
   checking the exact dataclass field set before field access; forged frozen
   instances must fail with `TypeError`/`ValueError` and the use case must
   return `invalid_request` for forged requests.

Add focused adversarial tests for custom `__deepcopy__` and extra attributes.
Preserve all prior contracts and rerun focused, M9/M8, architecture/schema,
compileall, diff-check, fresh independent review, ledger, commit, and push.
