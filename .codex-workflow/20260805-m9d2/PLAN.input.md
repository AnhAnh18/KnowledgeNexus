# M9-D2 Delta and Inventory Diff Propagation

Implement a bounded, read-only delta seam over approved M8-E document chunk
summaries and explicit inventory observations. The stage must not wire an
exporter, raw store, checkpoint, network client, metadata store, embedding
service, Qdrant, or clock.

## Required behavior

- Compare previous/current `DocumentChunkSetSummary` tuples by exact document
  identity.
- Short-circuit unchanged documents when `document_content_hash` is identical.
- Diff previous/current chunk IDs and content hashes. Emit `chunk` tombstones
  for disappeared IDs and same-ID content-hash changes with
  `content_updated`.
- Accept explicit current inventory state for previous documents:
  `present`, `source_deleted`, `access_revoked`, `moved_out_of_scope`, or
  `config_invalidated`. Missing current documents default to
  `source_deleted`; conflicting inventory/summary states fail atomically.
- When a document is removed or invalidated, emit one document tombstone with
  the selected reason and explicit previous chunk children through the M9-D1
  cascade. A changed document emits only affected chunk tombstones.
- A changed request-level config hash invalidates all previous documents that
  remain present, unless a more specific inventory state applies.
- Produce deterministic aggregate records, canonical bytes/digest, fixed
  metrics, zero partial records on any failure, and sanitized failure
  categories. Require `previous_dataset_version != current_dataset_version`.

## Public API and files

- `foundation/domain/models/delta_propagation.py`: runtime-validated
  `DeltaInventoryState`, `DeltaInventoryEntry`, `DeltaPropagationRequest`,
  `DeltaPropagationMetrics`, `DeltaPropagationStatus`,
  `DeltaPropagationFailureCategory`, and `DeltaPropagationResult`.
- `foundation/application/use_cases/propagate_delta.py`:
  `PropagateDelta(schema_validator=...).execute(request: object)`.
- Add additive exports and focused adversarial tests under domain models and
  application use cases.
- Reuse `ProjectTombstones` and `TombstoneTarget` for schema-valid record
  construction; do not change M9-D1 semantics or exporter behavior.

## Determinism and invariants

- Validate exact runtime types, forbidden extra fields, unique summary and
  inventory identities, profile/chunker consistency, non-empty versions,
  canonical RFC3339 timestamps, and JSON-safe defensive ownership.
- Sort documents by Unicode document ID and final records by fixed entity rank,
  entity ID, then tombstone ID. Identical duplicate records collapse; any
  same-ID canonical conflict fails atomically.
- Metrics must cross-check record count, document/chunk tombstone counts,
  changed-document count, and unchanged-document skip count.
- Results must reject impossible status/record/count/metrics combinations.

## Acceptance and validation

- Happy-path tests for unchanged, new, removed, access-revoked, out-of-scope,
  config-invalidated, changed-chunk, same-ID changed-hash, permutation, and
  duplicate cases.
- Adversarial tests for `object()`, `None`, wrong enums, missing/extra fields,
  forged summaries/inventory/result/metrics, invalid versions/hashes/timestamps,
  conflicting inventory states, impossible counters, malformed chunk IDs,
  schema-validator failures, and atomic no-partial-result behavior.
- Purity guards prove no filesystem/network/clock/export/checkpoint calls.
- Run focused tests, M9-D1/M8-D/E regressions, architecture, compileall,
  diff-check, fresh independent review, roadmap/state update, commit, push.
