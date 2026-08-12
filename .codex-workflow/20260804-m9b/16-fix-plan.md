# M9-B Re-review Fix Plan 4

Address only `15-review-5.md`:

- Reconstruct each fallback chunk's canonical prefix plus the exact source
  lines selected by its one-based `line_start`/`line_end` from the owning
  observation; reject any text that differs, even if its hash/ID/token count
  are recomputed.
- Require `authority_observations` to be exactly one sorted entry per authority
  path (no duplicates or arbitrary ordering).
- Add direct forged-body and duplicate-authority tests, then rerun all scoped
  validation and an independent review. Ledger updates remain blocked until
  `VERDICT: PASS`.
