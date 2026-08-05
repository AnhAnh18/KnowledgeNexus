# M9-B Re-review Fix Plan 10

Address only `28-review-12.md`:

- Treat `max_normalized_bytes` as the configured per-file limit, not an
  aggregate limit; retain aggregate raw-byte enforcement including excluded
  bytes.
- Revalidate snapshot metrics in the application before dereference and map
  malformed counters to `RESULT_INVALID`.
- Reject plan token counts greater than the assembled text length as
  impossible at the model boundary; application tokenizer validation remains
  authoritative for exact counts.

Rerun all validation and a fresh independent review before ledger updates.
