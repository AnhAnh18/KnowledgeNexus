# M9-D2 Bounded Test-Coverage Fix

Address only the P2 coverage finding in `09-review-2.md`.

- Add parameterized model tests for every outer summary missing/extra field.
- Add nested-entry tests for missing/extra fields, malformed ID/hash,
  invalid part metadata, and wrong entry runtime type.
- Add current-summary forged-input coverage and a validator/projector call
  counter proving malformed summaries fail before side effects.
- Keep production code unchanged and rerun focused M9-D2, regressions,
  architecture, compileall, diff-check, then obtain a fresh final review.
