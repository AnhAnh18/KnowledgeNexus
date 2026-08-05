# M9-B Re-review Fix Plan 14

Address only `36-review-16.md`:

- Apply strict LF-terminated decimal header parsing to `cat-file --batch`
  blob responses; reject signs, CR, leading-zero variants, and malformed
  sizes.
- Bind Git identity responses to exact expected single-line bytes (no
  `strip()` whitespace tolerance).
- Allow an empty pinned tree to produce an empty `cat-file --batch-check`
  response and empty snapshot.

Rerun all validation and a fresh independent review.
