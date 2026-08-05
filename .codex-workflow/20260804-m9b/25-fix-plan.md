# M9-B Re-review Fix Plan 8

Address only `24-review-10.md`:

- Deeply rerun `GitScanBudgets`, `GitSourceConfig`, and active
  `ChunkingProfile` validators at public reader/application boundaries.
- Revalidate each snapshot observation with `GitFileObservation.__post_init__`.
- Revalidate successful `GitCodeBuildResult` plans before accepting the success
  status.
- Require fallback coverage to start at source line 1 and advance without
  gaps; keep permitted overlap semantics.
- Guard tokenizer span access so missing/forged `spans` returns sanitized
  `TOKENIZER_FAILED`.

Add adversarial tests and rerun all validation plus a fresh independent review.
