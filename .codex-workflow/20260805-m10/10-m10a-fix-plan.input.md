# M10-A Boundary Validation Fix

Address only the P1/P2 findings in `.codex-workflow/20260805-m10/09-m10a-review-1.md`.

- Add exact-field and forged-instance revalidation for every public M10-A
  model: nested scope/exclusion/media policy, request, metrics, projection,
  result, and quality input. Missing attributes, forbidden extras, wrong
  runtime types, and impossible combinations must fail with sanitized typed
  errors before field access or side effects.
- Replace permissive `datetime.fromisoformat` checks with the approved strict
  RFC3339 grammar: timezone required, date-only and naive values rejected,
  canonical value preserved.
- Reject Windows reparse-point dataset roots in addition to symlinks, while
  keeping the fix bounded to the public request boundary and testable without
  filesystem mutation outside temporary fixtures.
- Add adversarial focused tests for every model and rerun M10-A focused tests,
  compileall, and diff-check before a fresh independent re-review.

Production scope remains limited to M10-A models/tests; no exporter, CLI,
orchestration, roadmap/state, or unrelated M8/M9 changes.
