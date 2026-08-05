# M9-D1 Fix Plan 2

Address only the five findings in `09-review-2.md`.

1. Recompute each result record's tombstone ID through
   `TombstoneIdGenerator` and reject mismatched preimages.
2. Re-run sentinel-safe `TombstoneProjectionMetrics.__post_init__` on nested
   metrics before reading cross-field values; forged metrics must raise typed
   errors.
3. Re-run `TombstoneTarget.__post_init__` for request root and every child
   before entity-field access so forged targets classify as `invalid_request`.
4. Permit explicit `null` for schema-optional `detail` and
   `source_version_last_seen`, while validating non-null values.
5. Strengthen builder post-validator integrity checks with exact key/value
   types, canonical JSON bytes, and no equality-only mutation acceptance.

Add focused adversarial tests for each finding. Preserve dependency
injection/purity, atomicity, no-I/O scope, and all prior regression commands.
