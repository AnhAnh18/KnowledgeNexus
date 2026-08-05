# M9-B Re-review Fix Plan 7

Address only `22-review-9.md`:

- Re-run `GitScanMetrics.__post_init__` at snapshot and plan boundaries so
  forged impossible counters cannot be published.
- Validate injected `GitCommandResult` fields (`returncode` exact int,
  stdout/stderr exact bytes) before interpreting the result.
- Make forged/missing request fields return sanitized `INVALID_REQUEST` before
  access; revalidate complete `GitSourceConfig` at the reader boundary before
  nested field dereferences.
- Add direct adversarial tests, rerun all validation, and obtain another fresh
  independent review before ledger updates.
