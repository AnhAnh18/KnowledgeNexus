# M6D-C Independent Review Summary

Date: 2026-07-22

Base: `740ede581a91de85e40c6aa276dc10f90186afe8`

Implementation head: `72e4826cf4831e5a2cfa481618190a5e6a570ac8`

## Verdict

Approve after focused independent re-review.

The structural parser, M6C adapter, and production parser output satisfy the
M6D-C boundary. One P2 was reproduced in the public domain model contract:
frozen dataclasses retained caller-owned mutable lists for structural
collections. Mutating those lists changed the supposedly immutable structure
after construction and could make it unhashable.

The review candidate now copies ordered sequences into tuples and rejects
scalar strings/bytes, unordered collections, and invalid entry types. Claude
performed the focused independent re-review, confirmed the working tree exactly
matches the small fix patch, and approved M6D-C with no remaining P0-P3 finding.

## Verification

- `git diff --check 740ede5..72e4826`: pass.
- Original focused M6D-C suite: 86 passed.
- Original broad offline battery: 1,065 passed.
- Focused suite after the immutability fix: 93 passed.
- Broad offline battery after the fix: 1,072 passed.
- Claude focused re-review independently reproduced both final counts and
  approved the fix.
- No live request or production artifact was used.

## Boundary

- Pure structural parsing only.
- No filesystem, network, tokenizer, token budget, packing, overlap, chunk ID,
  `ChunkRecord`, ACL, relation, media, or export implementation.
- M6D-D has not started.
