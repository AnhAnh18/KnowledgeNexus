RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# Plan Critique

The bounded, read-only intent is appropriate and the plan correctly reuses the
M8-E summaries and M9-D1 tombstone seam. It is not yet execution-ready: several
public contracts and precedence rules are implicit, and the current Foundation
contracts impose constraints that are not reflected in the acceptance list.

## Blocking Gaps and Risks

1. **The public model contract is incomplete (P1).** The plan names six models
   and a use case but does not define their exact fields, defaults, constructor
   behavior, or success/failure return policy. Specify the request fields at
   minimum: previous/current dataset versions, previous/current config hashes,
   an explicit caller-supplied `detected_at` timestamp (the seam must not read a
   clock), previous/current `tuple[DocumentChunkSetSummary, ...]`, and inventory
   entries. State that `execute(request: object)` rejects `object()`, `None`,
   subclasses, and forged instances before field access and returns one typed
   failed result rather than leaking an exception.

2. **Inventory state precedence is ambiguous (P1).** Define the complete
   truth table. A previous document missing from current summaries defaults to
   `source_deleted`; a current summary normally implies `present`; an explicit
   `present` without a current summary and any non-present state with a current
   summary must fail atomically. Define whether an inventory entry for a new
   document is rejected or must be `present`, whether duplicate identical
   entries collapse, and that conflicting entries fail. Define precedence as
   specific inventory states (`source_deleted`, `access_revoked`,
   `moved_out_of_scope`, `config_invalidated`) over request-level config
   invalidation, with no silent merging of reasons.

3. **Delta request fields and hash policy are underspecified (P1).** Name the
   config fields and require lowercase 64-hex SHA-256 values (or explicitly
   document another Foundation-approved grammar). Define changed-config as
   exact hash inequality, and define what happens when the active profile or
   chunker version differs. `CHUNKING_SPEC.md` requires the unchanged
   short-circuit to consider both document content hash and chunker version;
   M8-E currently accepts only the active Confluence profile/chunker. Either
   reject stale/unsupported summaries before diffing or specify a reviewed
   invalidation path; do not accidentally treat a chunker change as ordinary
   content change.

4. **M8-E identity scope is not stated (P1).** `DocumentChunkSetSummary` and
   its builder currently enforce `confluence:page:<non-space>` document IDs,
   `confluence`/`wiki_page` records, and the active profile. M9-B/C introduce
   Git identities, but they are not representable by the current M8-E summary
   builder. Explicitly make this stage Confluence-only (reject Git summaries)
   or add a separately authorized summary contract; do not imply that M9-B/C
   records are accepted by this API without defining their identity/profile
   rules. Revalidate every typed summary before accessing fields, including
   `object.__new__` forged instances and hostile string subclasses.

5. **Tombstone materialization semantics are incomplete (P1).** State that
   output records are Foundation `TombstoneRecord` dictionaries only: new
   documents/chunks are not emitted by this tombstone-only seam. For an
   invalidated/removed document, invoke the existing `ProjectTombstones` once
   with a document root plus every previous chunk as explicit children; M9-D1
   applies one reason to root and children. For a changed, present document,
   invoke chunk-root projections only for disappeared IDs and same-ID hash
   changes; additions and unchanged IDs produce no tombstones. Define how
   `detail` and `source_version_last_seen` are sourced (if at all), including
   omitted versus explicit `null`, and preserve D1's optional-field limits.

6. **Ordering, duplicate, and collision policy is not normative (P1).** Publish
   the exact aggregate rank already used by M9-D1 (`document=0, chunk=1,
   media=2, relation=3, acl=4, symbol=5`) and exact Unicode/code-point ID
   ordering. Define whether duplicate canonical records collapse globally,
   what constitutes a same-ID canonical conflict, and how a generated
   tombstone-ID collision is categorized. Input permutation must not affect
   records, bytes, metrics, or digest. Do not broaden `ProjectTombstones` to a
   multi-root API; collect per-document/per-chunk projections and aggregate
   them in this new use case so M9-D1 semantics remain unchanged.

7. **Canonical result and zero-record success are unspecified (P1).** Define
   the exact result payload and serialization: sorted-key compact UTF-8 JSON,
   `ensure_ascii=False`, `allow_nan=False`, and SHA-256 digest over those bytes.
   Say whether bytes cover status/metrics/error fields as M9-D1 does or only
   records. A valid all-unchanged request must be a successful result with zero
   records; the result model and metrics must permit that (unlike the D1
   single-cascade result). A failed result must have no records, count, metrics,
   bytes-derived digest, or leaked exception text.

8. **Metrics and typed invariants need exact fields (P1).** List the metrics
   fields and equations, including total record count, document tombstone
   count, chunk tombstone count, changed-document count, unchanged-document
   skip count, and (if exposed) new-document count. Require all counters to be
   exact non-negative `int` (reject `bool`), and cross-check them against the
   final deduplicated records and document classification. Define whether an
   empty previous/current set is valid and how `previous_dataset_version !=
   current_dataset_version` interacts with an otherwise empty result.

9. **Atomic validation and failure taxonomy are underdefined (P1).** Specify
   the finite sanitized failure categories and mapping for malformed request,
   summary, inventory, version/hash/timestamp, state conflict, duplicate or
   tombstone-ID collision, dependency, schema-validator failure, and internal
   failure. Validate all summaries/inventory entries and config/version fields
   before any projection; retain all records in local temporaries; if a later
   document or validator fails, return zero records. Validator construction and
   attribute lookup must be guarded, and exception messages/raw IDs/content must
   never cross the boundary.

10. **Purity and integration boundaries need executable scope (P2).** Name the
    only production files allowed (the two requested modules and additive
    `__init__` exports) and explicitly prohibit schema, exporter, manifest,
    checkpoint, metadata-store, raw-store, filesystem, network, environment,
    clock, embedding, Qdrant, and ACL-resolver wiring. Add architecture/import
    checks and monkeypatch guards for `open`/`Path`, sockets/HTTP, clocks,
    exporters, checkpoints, and raw stores. Existing full-snapshot exporters
    must remain tombstone-empty unless this use case is explicitly called.

## Required Acceptance and Test Additions

- Constructor and boundary probes for `object()`, `None`, wrong container
  types, subclasses, missing/forbidden fields, wrong enum values, booleans in
  counters, forged summaries/inventory/metrics/results, cyclic JSON values,
  hostile attribute access, and mutation after construction.
- A table-driven inventory matrix covering every state, missing-current default,
  current-summary/state conflicts, duplicate identical/conflicting entries,
  new-document entries, config-change precedence, and atomic failure.
- Happy paths for empty/all-unchanged, new, removed, access-revoked,
  moved-out-of-scope, config-invalidated, changed-document with disappeared
  chunks, same-ID hash changes, mixed documents, and added-plus-unchanged
  chunks (assert additions are omitted from this tombstone-only output).
- M8-E compatibility tests for active profile/chunker, stale profile/chunker,
  Confluence versus Git IDs, duplicate summary identities, malformed IDs and
  hashes, summary permutation, same document hash with differing entries, and
  exact Unicode ordering.
- Determinism tests that permute summaries/inventory/children and assert equal
  records, canonical bytes, digest, and metrics; duplicate identical records
  collapse, while same-ID canonical conflicts and generated-ID collisions fail.
- Schema-validator tests for construction/lookup/record rejection failures and
  a late failure proving no partial records escape. Verify every emitted record
  with the Foundation tombstone schema and unchanged M9-D1 cascade semantics.
- Result/metrics forgery tests for impossible status/count/record combinations,
  zero-record success, and defensive ownership of nested record data.
- Purity guards plus architecture tests, focused domain/use-case tests,
  M9-D1/M8-D/E regressions, `compileall`, scoped `git diff --check`, and a
  fresh independent review in a separate session. Update roadmap/state only
  after implementation and independent approval; do not claim the M8-AC real
  corpus gate or wire M10/export behavior.

## Recommended Implementation Shape

Keep M9-D1 unchanged. Build a validated, immutable request and classification
pass first; resolve inventory/config precedence into explicit document actions;
materialize each action through `ProjectTombstones`; then globally deduplicate,
sort, validate, count, canonicalize, and construct the result. This sequencing
provides the required all-or-nothing behavior and makes every cross-field
invariant testable without adding any I/O or exporter integration.
