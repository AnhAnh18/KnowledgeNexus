# M9-B Re-review Fix Plan 12

Address only the latest review findings:

- Map any injected runner exception, including forged `GitCodeBuildError`, to
  sanitized `REPOSITORY_READ_FAILED` at the Git adapter boundary.
- Enforce `max_file_bytes` immediately after blob size resolution for every
  tree entry, including generated/vendor/binary exclusions.
- Add adversarial tests and run full scoped validation plus a fresh review.
