RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-D1 Fix Plan 2 - Reviewed

## Objective

Address only the five confirmed findings in `09-review-2.md` while preserving
the injected-validator, no-I/O, atomicity, ordering, and exporter-boundary
contracts already established by M9-D1. Do not change schemas, cascade policy,
exporters, stores, checkpoints, roadmap state, or unrelated modules.

## Implementation steps

1. **Deterministic result IDs**

   In `foundation/domain/models/tombstone_propagation.py`, after validating the
   record fields and dataset version, recompute the expected ID with
   `TombstoneIdGenerator.generate_tombstone_id(entity_type, entity_id, reason,
   dataset_version)`. Reject any mismatch, including a grammatically valid
   all-zero or otherwise forged ID, before accepting a success result. Keep the
   existing ID grammar check and add a focused mismatch test.

2. **Nested metrics revalidation**

   In `TombstoneProjectionResult.__post_init__`, use sentinel-safe reads and
   exact-type checks for `metrics`, then explicitly invoke
   `TombstoneProjectionMetrics.__post_init__(metrics)` before reading
   `record_count`, `root_count`, or `child_count`. A forged metrics object with
   impossible counts or missing fields must raise only `TypeError`/`ValueError`,
   never leak `AttributeError`, and cannot produce a successful result. Retain
   the result-level count and status invariants after nested validation.

3. **Nested target revalidation and classification**

   In `TombstoneProjectionRequest.__post_init__`, after exact-type checks and
   before reading entity fields, call `TombstoneTarget.__post_init__` for the
   root and every child. Use the existing sentinel-safe model validation so
   missing or forged target attributes become typed errors. In
   `ProjectTombstones.execute`, map all request/target revalidation
   `TypeError`/`ValueError` failures to `invalid_request`; do not call the
   injected validator for these failures. Preserve duplicate and cascade
   validation behavior after all targets are valid.

4. **Schema-compatible nullable optionals**

   Update the result record validator to accept an explicitly present
   `detail: None` or `source_version_last_seen: None`, matching
   `tombstone_record.schema.json`. For non-null values retain the current
   string, one-line/size, and non-empty/no-whitespace checks. Continue rejecting
   wrong types, extra keys, missing required keys, and non-JSON-safe values.

5. **Canonical builder mutation guard**

   In `TombstoneRecordBuilder.build`, define the expected key set and exact
   value-type/JSON shape before validation. Capture canonical JSON bytes of the
   pre-validation record (with the established sorted-key, compact UTF-8
   serialization), call the injected validator, then compare both the exact key
   set and canonical post-validation bytes. Reject equal-but-different values
   such as `str` subclasses, non-canonical replacements, optional-key drift,
   and any mutation that makes serialization fail. Ignore any return value from
   `validate_record`; return a fresh plain dictionary only after all checks pass.

## Files and scope

Modify only the existing tombstone model, builder, use case if needed for
classification, and focused tests. Keep additive exports and the required
validator injection unchanged. Do not restore a default `FoundationSchemaValidator`,
perform schema filesystem loading in `ProjectTombstones`, or wire this seam into
exporters.

## Required adversarial tests

- **Result ID:** valid records for every entity/reason combination plus a valid
  grammar with a mismatched deterministic preimage; assert construction fails.
- **Forged metrics:** `object.__new__(TombstoneProjectionMetrics)` with missing
  fields, impossible cross-field counts, wrong types, and forged values nested
  in a success result; assert only `TypeError`/`ValueError` and no success.
- **Forged targets:** forged root and child targets with missing fields, wrong
  enum, malformed IDs, and invalid optional metadata; direct request validation
  and `execute` must produce typed invalid-request failures, zero records/count,
  one sanitized category, and zero validator calls. Include `object()`, `None`,
  wrong containers/subclasses, missing required fields, and forbidden extra
  fields at each public/application boundary.
- **Nullable optionals:** schema-shaped records with each optional key absent,
  string, and explicit `None`; reject wrong types, newline/oversized detail,
  and invalid source versions.
- **Builder integrity:** validators that mutate a value, add/remove keys,
  replace a value with an equal-comparing `str` subclass, mutate then raise, or
  return a replacement; assert fail-closed behavior and no partial output.
- **Atomicity/regressions:** a malformed later child, builder failure, validator
  failure, or result validation failure returns no records and count zero;
  preserve deterministic ordering, purity guards, dependency-injection tests,
  and unchanged exporter behavior.

## Verification

Run the focused tombstone model/builder/use-case tests, then the prior M9-D1,
M9-A/B/C, M8-D/E, architecture, and integration regression commands. Run
`python -m compileall -q src tests` and `git diff --check`. If pytest temp-root
permissions reproduce the review environment error, rerun with an explicit
workspace-local `--basetemp` and report the exact command/result. Acceptance
requires all relevant tests to pass, no filesystem/network/clock side effects,
and a fresh independent review in a new CLI session.
