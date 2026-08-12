# M9-B Re-review Fix Plan 9

Address only `26-review-11.md`:

- Enforce snapshot `seen <= max_tree_entries` and included observation count
  `<= max_files` in the application validator.
- Revalidate each observation with `GitFileObservation.__post_init__` before
  dereferencing fields; map malformed forged observations to a sanitized
  result-invalid category.
- Require the final fallback window to end at the owning source's final line,
  preventing line-1-only plans for multi-line files.
- Add adversarial tests and rerun validation plus independent review.
