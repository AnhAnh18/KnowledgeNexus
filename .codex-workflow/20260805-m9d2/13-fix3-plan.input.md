# M9-D2 Application-Boundary Coverage Fix

Address only the P2 finding in `12-review-final.md`.

- Add execute-level parameterized malformed-summary coverage for every outer
  summary missing/extra field and every nested entry missing/extra/malformed
  case in both `previous_summaries` and `current_summaries`.
- Assert atomic `SUMMARY_INVALID` results and zero schema-validator/projector
  calls for every malformed case.
- Keep production code unchanged; update only the focused M9-D2 tests and
  rerun the bounded validation suite before a fresh independent review.
