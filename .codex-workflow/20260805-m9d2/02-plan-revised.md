# M9-D2 Delta and Inventory Diff Propagation - Revised Plan

## Review disposition

The independent critic classified this stage as `complex`. This revision fixes
the public-field, precedence, M8-E compatibility, deterministic output,
metrics, atomicity, and adversarial-test gaps before implementation.

## Public API and exact inputs

### `DeltaInventoryState`

Closed enum values:
`present`, `source_deleted`, `access_revoked`, `moved_out_of_scope`, and
`config_invalidated`.

### `DeltaInventoryEntry`

Exact immutable fields:

- `document_id: str` matching the M8-E Confluence document ID grammar;
- `state: DeltaInventoryState`;
- `source_version_last_seen: str | None` (non-empty opaque string when set).

Entries are current-observation overrides for a previous document. IDs are
unique; a duplicate with different state/version is an atomic
`inventory_conflict`.

### `DeltaPropagationRequest`

Exact immutable fields:

- `previous_dataset_version: str`;
- `current_dataset_version: str` (must differ from previous);
- `previous_config_hash: str` and `current_config_hash: str` (lowercase
  64-hex SHA-256 strings);
- `detected_at: str` (RFC3339, normalized to UTC microseconds and `Z`);
- `previous_summaries: tuple[DocumentChunkSetSummary, ...]`;
- `current_summaries: tuple[DocumentChunkSetSummary, ...]`;
- `inventory: tuple[DeltaInventoryEntry, ...] = ()`.

Summary IDs are unique in each tuple. M8-E summaries already enforce
Confluence document identity, active profile identity, active chunker version,
chunk ID/hash/part/count invariants, and canonical ownership; the request
revalidates exact types and immutable state before field access. No other
source-system summary type is accepted in this bounded stage.

### `PropagateDelta`

`PropagateDelta(schema_validator=...).execute(request: object)` is the only
application boundary. The schema validator is mandatory dependency injection;
construction performs no filesystem loading. The use case reuses
`ProjectTombstones` for every document or chunk tombstone and returns an
aggregate `DeltaPropagationResult`.

## Inventory precedence and diff semantics

For each document in the union of previous/current IDs, apply this exact
decision table:

1. An inventory entry for a new document (not in previous) is invalid unless
   its state is `present`; no tombstone is emitted for a new document.
2. A previous document with an explicit non-`present` inventory state must have
   no current summary; otherwise return `inventory_conflict`. Emit one
   document-root cascade with that state mapped to the same `TombstoneReason`.
3. A previous document absent from current summaries and absent from inventory
   defaults to `source_deleted`, emitting one document-root cascade.
4. A current document with no previous summary is new; emit no tombstones.
5. A document present in both summaries with inventory absent or `present` is
   eligible for content/config comparison. Any non-present state is invalid.
6. If config hashes differ, every previous/current document eligible under rule
   5 emits one `config_invalidated` document-root cascade containing all
   previous chunk IDs. This global invalidation takes precedence over content
   chunk diffing, but explicit non-present inventory state takes precedence over
   global config invalidation.
7. If config hashes match and document content hashes are equal, emit nothing
   and increment `unchanged_document_count` (no chunk inspection side effect).
8. If config hashes match and document content hashes differ, compare previous
   and current chunk entries. Emit `content_updated` chunk tombstones for every
   previous chunk ID that disappeared or whose same ID has a different content
   hash. New-only chunks produce no tombstones. If the document hash changes but
   no old chunk is removed/changed, emit no record but count the document as
   changed.

Document cascades use the previous summary's chunk IDs as explicit `chunk`
children. Changed-document diffing is chunk-only; this stage emits no
additions/upserts and does not mutate exports or state. `source_version_last_seen`
is preserved on the document root when supplied by inventory; chunk tombstones
have no inferred source version.

## Result contract

`DeltaPropagationStatus` is `success` or `failed`. Failure categories are
exactly `invalid_request`, `invalid_dependency`, `summary_invalid`,
`inventory_conflict`, `tombstone_failure`, `result_invalid`, and
`internal_failure`.

`DeltaPropagationMetrics` exact fields:

- `document_count` (union size);
- `new_document_count`, `unchanged_document_count`, `changed_document_count`,
  `removed_document_count`;
- `document_tombstone_count`, `chunk_tombstone_count`, `record_count`.

Invariants: union count equals the four document-state counts; record count
equals document plus chunk tombstones; document/chunk counts equal the actual
record entity types; unchanged and new documents have no tombstone records;
all values are exact non-negative integers. A successful empty delta is valid
with `count=0` and all metrics zero. Failure always has `records=()`,
`count=0`, `metrics=None`, and one category.

The result carries `base_dataset_version`, `dataset_version`, ordered immutable
records, and a SHA-256 digest over compact sorted-key UTF-8 JSON. Records are
sorted by fixed entity rank (`document`, `chunk`, `media`, `relation`, `acl`,
`symbol`), Unicode entity ID, then tombstone ID. Identical canonical records
collapse; same-ID records with different canonical bytes return
`result_invalid` atomically. Typed result construction validates exact
tombstone shape/ID preimages through the M9-D1 model boundary, JSON safety,
forbidden extra fields, and all cross-field metrics.

## Module boundaries and purity

- Add `foundation/domain/models/delta_propagation.py`.
- Add `foundation/application/use_cases/propagate_delta.py` and additive
  package exports.
- Add focused model/use-case tests only; do not alter M8-D/E or M9-D1
  semantics, schemas, exporters, staging writers, manifest builders, raw
  stores, checkpoints, ACL/media/Git/symbol processors, or consumer modules.
- No filesystem, network, environment, clock, exporter, checkpoint, raw-store,
  metadata-store, embedding, Qdrant, or external resolver calls. The only time
  operation is parsing the caller-provided timestamp.

## Acceptance and validation

- Happy-path coverage for empty, new, unchanged, changed chunk, same-ID hash
  change, source deletion, access revocation, out-of-scope, config invalidation,
  permutation-independent ordering, duplicate collapse, and collision failure.
- Adversarial coverage for `object()`, `None`, wrong enum/containers, missing
  and forbidden extra fields, forged summaries/inventory/result/metrics,
  invalid versions/hashes/timestamps, malformed chunk IDs, impossible counters,
  conflicting inventory states, validator rejection/mutation, and atomic
  zero-partial-result behavior.
- Run focused M9-D2 tests, M9-D1/M8-D/E regressions, M9-A/B/C regressions,
  architecture, compileall, `git diff --check`, fresh independent review and
  any bounded fix/re-review. Update roadmap/state only after final PASS, then
  commit and push.
