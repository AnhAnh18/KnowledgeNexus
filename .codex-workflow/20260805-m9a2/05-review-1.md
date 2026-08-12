# M9-A2 Independent Review 1

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Findings

- P1: Fetch/store port errors accept arbitrary constructor arguments and
  preserve arbitrary strings in `str`/`repr`; this can leak IDs, paths, bytes,
  hosts, or underlying exception text across the public boundary.
- P1: `FetchAndStoreConfluenceAttachmentBody` trusts forged exact dataclass
  instances. `object.__new__(RawHttpObservation)` and
  `object.__new__(MediaBodyStoreBudget)` reach field access and leak
  `AttributeError` instead of sanitized category failures.
- P1: Unexpected `RuntimeError` (and other non-listed exceptions) from the
  fetcher or raw store propagates unsanitized, violating the failure mapping
  and atomic boundary contract.
- P1: Concurrent publishes can both pass cumulative budget checks and exceed
  `max_total_bytes`; budget accounting has no reservation/serialization guard.
- P2: `_scan_tree` is recursively unbounded and scan exceptions can escape the
  publication boundary instead of mapping to a stable store category.
- P2: `MediaAttachmentRawArtifact.__repr__` exposes byte counts at a public
  boundary despite the strict no-sensitive-metadata error/repr rule.

## Verdict

VERDICT: CHANGES_REQUIRED
