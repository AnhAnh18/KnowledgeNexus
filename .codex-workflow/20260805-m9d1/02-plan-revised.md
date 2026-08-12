# M9-D1 Tombstone Contract and Cascade - Revised Plan

## Review disposition

The independent critic classified the stage as `complex`. This revision makes
the public API, ID policy, optional fields, canonical ordering, duplicate
handling, timestamp normalization, and atomic failure contract explicit.

## Public API and module boundaries

- `foundation/domain/models/tombstone_propagation.py`: enums
  `TombstoneEntityType`, `TombstoneReason`, `TombstoneProjectionStatus`,
  `TombstoneProjectionFailureCategory`; immutable `TombstoneTarget`,
  `TombstoneProjectionRequest`, `TombstoneProjectionMetrics`, and
  `TombstoneProjectionResult`.
- `foundation/domain/rules/tombstone_record_builder.py`:
  `TombstoneRecordBuilder.build(...) -> dict[str, object]`.
- `foundation/application/use_cases/project_tombstones.py`:
  `ProjectTombstones.execute(request: object) -> TombstoneProjectionResult`.
- Exports are additive under existing Foundation `models`, `rules`, and
  `application.use_cases`; no exporter is wired to this seam in M9-D1.

Invalid public requests return a sanitized failed result from `execute`; direct
model/builder constructors raise `TypeError`/`ValueError` before field access.
Unexpected dependency exceptions are converted to `internal_failure` and no
partial records escape.

## Target and ID contract

`TombstoneTarget` fields are exactly:

- `entity_type: TombstoneEntityType`;
- `entity_id: str`;
- `detail: str | None` (NFC, one-line, maximum 1024 UTF-8 bytes);
- `source_version_last_seen: str | None` (non-empty, no whitespace).

Entity ID validation follows the schema's opaque-ID rule (non-empty, no
whitespace) for `document`, `media`, and `symbol`; it uses the authoritative
shared grammars for `chunk`, `relation`, and `acl`:

- chunk: `chunk:(confluence|git):[0-9a-f]{16}(-[0-9]+)?`;
- relation: `rel:[0-9a-f]{16}`;
- acl: `acl:\S+`.

The existing `TombstoneIdGenerator` remains the sole ID algorithm. Its input is
`entity_type.value`, `entity_id`, `reason.value`, and `dataset_version`; detail,
timestamp, and source version never affect the tombstone ID.

## Request/result semantics

`TombstoneProjectionRequest` fields are exactly `root: TombstoneTarget`,
`reason: TombstoneReason`, `detected_at: str`, `dataset_version: str`, and
`children: tuple[TombstoneTarget, ...]`.

- `detected_at` is a required RFC3339 timestamp; normalize it to UTC with
  microseconds and `Z` once at construction. Naive/invalid timestamps fail.
- `dataset_version` is a non-empty, no-whitespace string; source versions are
  non-empty, no-whitespace strings when present.
- A document root may have zero or more explicitly supplied children. Every
  other root must have an empty child tuple; no child is inferred and no
  child-to-parent cascade exists.
- All children receive the same reason, dataset version, and detected time as
  the request. Root/child detail and source-version metadata remain local to
  each target; they are not copied implicitly.
- Duplicate key `(entity_type, entity_id, reason, dataset_version)` collapses
  only when all target metadata is byte-identical. Any metadata conflict fails
  atomically; duplicate IDs caused by distinct preimages fail closed.

`TombstoneProjectionResult` fields are exactly `status`, `records`, `count`,
`metrics`, and `error_category`. Success requires `status=success`, a tuple of
  schema-shaped dicts, `count == len(records)`, matching metrics, and no error;
failure requires `status=failed`, `records=()`, `count=0`, `metrics=None`, and
exactly one `TombstoneProjectionFailureCategory`.

## Record shape and ordering

`TombstoneRecordBuilder` creates exactly the schema fields:
`schema_version`, `tombstone_id`, `entity_type`, `entity_id`, `reason`,
`detected_at`, `dataset_version`; it adds `detail` and
`source_version_last_seen` only when non-null. It invokes
`FoundationSchemaValidator.validate_record("TombstoneRecord", record)` before
returning a defensive plain dict.

Records are sorted by fixed rank then Unicode code-point entity ID:
`document=0`, `chunk=1`, `media=2`, `relation=3`, `acl=4`, `symbol=5`.
Canonical bytes use `json.dumps(..., ensure_ascii=False, sort_keys=True,
separators=(",", ":"), allow_nan=False).encode("utf-8")`.

## Cascade and purity

The normative document cascade is explicit only: document root, then supplied
chunks, media, relations, ACL, and symbols. Every one of the five reasons uses
the same cascade shape; the caller chooses which children are present. Child
targets with a different entity type or repeated ID are validated using the
same rules. No filesystem, clock, environment, network, exporter, checkpoint,
raw-store, ACL resolver, Qdrant, or metadata-store call is allowed; the only
time operation is parsing the caller-provided timestamp.

## Acceptance tests

- Schema golden tests for required/optional fields, exact key set, all enums,
  IDs, canonical timestamps, canonical bytes, and validator exceptions.
- Adversarial constructors/use case: `object()`, `None`, wrong enum values,
  missing/extra fields, wrong containers/subclasses, bool counters, malformed
  IDs, invalid/naive timestamps, oversized/newline detail, and forged frozen
  objects; fail before dependency calls.
- Cascade table for every reason, document/non-document roots, all entity
  types, empty/maximal children, permutation-independent ordering, duplicate
  identical/conflicting targets, and no inferred children.
- Atomic rollback when a later child, builder, or schema validator fails;
  result has no records/count leakage and only a sanitized category.
- Purity guards for file/network/clock/export/checkpoint/raw/ACL/Qdrant calls;
  current full-snapshot/export tests remain unchanged and tombstone-empty unless
  this seam is explicitly invoked.
- Focused tests, relevant M9 regressions, architecture, compileall,
  `git diff --check`, fresh independent review, ledger update, commit/push.

