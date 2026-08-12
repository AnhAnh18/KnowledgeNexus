# M9-B Re-review Fix Plan 6

Address only `20-review-8.md`:

- Require exact string runtime types for snapshot repository/branch/commit
  identity before equality comparisons and before application plan creation.
- Require forged `BuildGitCodeDocumentsRequest` nested `GitSourceConfig` and
  `ChunkingProfile` values to be exact runtime types before any field access or
  dependency call.
- Add adversarial tests for forged snapshot identity and nested request proxy
  values, then rerun all validation and independent review.
