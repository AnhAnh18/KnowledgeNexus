# M6G-A Contract Review Summary

Status: independently approved.

## Provenance

- `SOURCE_REVIEW_BASE`: `56e7750`.
- Approved `SOURCE_REVIEW_HEAD`: `dbe5c2f`.
- The approved change contains only the active focused contract,
  `START_HERE.md`, and the two durable state documents.
- These working-repository SHAs are provenance only and are not mandatory
  checkout targets in an independent main-machine repository.

## Verdict

- P0: none.
- P1: none.
- P2: none.
- M6G-A is approved and may be frozen as the contract base for M6G-B.

The reviewer verified the M6F result shape, C2 exit mapping, existing M3 APIs,
staging-path compatibility, locked dataset/source identities, focused-spec
precedence, and the absence of production implementation.

## Non-blocking P3

1. Add a contract-consistency test during M6G-B. Prefer assertions that bind
   implementation constants and behavior to the active specification over
   markdown-only string matching.
2. Treat the existing byte-for-byte M4 golden full-snapshot test as a mandatory
   M6G-C acceptance gate. The default M3 completer path must retain its exact
   historical output when no M6G quality extension is supplied.

## Boundary

- No M6G production code exists at the approved M6G-A head.
- M6G-B is the next planning task.
- M6G-C, M6G-D, and M7 remain blocked by their preceding gates.
- M6 overall remains incomplete until the real one-page snapshot is exported
  and accepted.
