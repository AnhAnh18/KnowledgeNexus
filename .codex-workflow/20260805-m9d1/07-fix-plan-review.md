RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D1 Bounded Fix Plan - Reviewed

## Objective

Address exactly the four confirmed independent-review findings in the existing
M9-D1 tombstone seam. Preserve the public behavior and scope from
`02-plan-revised.md`; do not add exporter wiring, persistence, roadmap work, or
new tombstone policy.

## Findings mapped to changes

1. **Validator mutation/field drift:** harden
   `foundation/domain/rules/tombstone_record_builder.py` so the record is
   snapshotted before `validate_record`, then compared after validation using
   canonical JSON bytes and the exact expected key set. Any validator mutation,
   optional-key insertion/removal, value change, or non-JSON-safe mutation must
   raise a sanitized-safe `ValueError`/schema-validation exception and return
   no record. Return a fresh plain dictionary only after the post-validation
   comparison; do not trust a validator return value.

2. **Result record contract:** strengthen
   `foundation/domain/models/tombstone_propagation.py` so
   `TombstoneProjectionResult.__post_init__` validates every record against the
   tombstone schema shape without loading files: exact required keys, optional
   key/null semantics, `SCHEMA_VERSION`, all enum strings, tombstone ID grammar
   and deterministic preimage, per-entity ID grammar, canonical timestamp,
   non-empty/no-whitespace dataset version, detail/source-version types, and
   JSON-safe values. Reject extra/missing keys and malformed values before any
   field-dependent access. Preserve the existing success/failure invariants:
   success has metrics, no error, and `count == len(records) == metrics.record_count`
   with root/child counts consistent; failure has `records == ()`, `count == 0`,
   `metrics is None`, and exactly one failure category.

3. **Forged frozen models:** make every affected model `__post_init__`
   (`TombstoneTarget`, `TombstoneProjectionRequest`,
   `TombstoneProjectionMetrics`, and `TombstoneProjectionResult`) use a shared
   sentinel-safe attribute reader. Missing or forged attributes must raise only
   `TypeError` or `ValueError`, never leak `AttributeError`. Revalidate nested
   forged targets/metrics/results explicitly before dereferencing their fields.
   In `ProjectTombstones.execute`, revalidation failures for an exact-type
   `TombstoneProjectionRequest` map to `invalid_request`; validator calls must
   not occur for such requests.

4. **Injected validator dependency:** change
   `ProjectTombstones.__init__` to require a `schema_validator` argument with a
   callable `validate_record`; remove the `FoundationSchemaValidator()` default
   and any construction that can load schemas from the filesystem. Keep the
   injected object as the only validator dependency. Update focused callers and
   tests to inject a real validator or a test double explicitly. A missing,
   `None`, or non-callable dependency fails at construction with `TypeError`;
   no exporter or application composition root is wired in this stage.

## File and scope boundary

Expected implementation files are the existing tombstone model, builder, use
case, and their focused tests. Additive package exports may remain as already
implemented. Do not modify JSON schemas, exporters, stores, checkpoint code,
network clients, roadmap/state files, or unrelated M9/M8 modules.

## Required tests

- **Builder mutation tests:** validators that mutate a value, add/remove a key,
  mutate optional fields, return a replacement value, or raise after mutation;
  assert the builder fails closed and no mutated/partial dictionary is returned.
- **Exact result-shape tests:** valid records for every entity type/reason and
  optional-field combination; reject `object()`, `None`, wrong enum strings,
  missing required keys, forbidden extra keys, wrong field types, malformed
  IDs, wrong schema version, non-canonical/invalid timestamps, whitespace or
  empty versions, invalid detail/source-version values, non-finite numbers, and
  deterministic-ID mismatches.
- **Forged-object tests:** create each model with `object.__new__`, omit fields,
  inject wrong field types, forge nested targets/metrics, and call
  `__post_init__`; assert only `TypeError`/`ValueError`. Exercise forged request
  execution and verify `invalid_request`, zero records/count, and zero validator
  calls. Include constructor missing/extra-field cases and wrong runtime
  containers/subclasses.
- **Dependency tests:** `ProjectTombstones()` (missing argument), `None`, and a
  non-callable validator fail at construction; an injected validator is used
  without filesystem access. Keep the existing schema-rejection sanitization
  and atomic rollback tests.
- **Adversarial application-boundary pass:** `execute(object())`, `execute(None)`,
  malformed requests, impossible result/metric counters, and dependency
  failures must fail closed before field access or side effects, with one
  sanitized category and no partial records.

## Verification and acceptance

Run the focused tombstone model/builder/use-case tests, then the prior M9-D1,
M9-A/B/C, M8-D/E, architecture, and integration regressions. Also run
`python -m compileall -q src tests` and `git diff --check`. Acceptance requires
all tests pass, no exporter output changes, no implicit schema/filesystem access
from `ProjectTombstones`, and a fresh independent review in a new session.
