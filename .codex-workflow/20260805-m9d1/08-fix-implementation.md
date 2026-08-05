# M9-D1 Fix Implementation Report

Applied only the reviewed fixes for the four independent-review findings.

- Validator mutation is detected before a tombstone record is returned.
- Results require exact schema-shaped tombstone dictionaries, canonical IDs,
  timestamps, enums, optional fields, JSON-safe values, and root metrics.
- Sentinel-safe model validation rejects forged frozen instances with typed
  errors; forged requests return `invalid_request`.
- `ProjectTombstones` now requires an injected schema validator, removing
  implicit filesystem contract loading from the pure application seam.

Validation:

- Focused M9-D1 fix suite: `19 passed`.
- Tombstone/export regression selection: `32 passed`.
- Architecture suite: `86 passed`.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed (line-ending normalization warnings only).

Second bounded fix pass:

- Result models now recompute deterministic tombstone IDs, revalidate nested
  metrics, and accept schema-permitted explicit null optionals.
- Requests revalidate root/child targets before field access.
- Builder mutation checks use exact key/value types plus canonical JSON bytes.
- Focused M9-D1 suite after the second pass: `23 passed`.

Third bounded fix pass:

- Model field sets are exact and reject forged extras.
- Result records are validated before defensive copying, preventing custom
  copy-hook execution or exception leakage.
- Focused M9-D1 suite: `28 passed`; M9/M8 boundary regression: `42 passed`;
  architecture/schema slice: `37 passed`; compileall and diff-check passed.

Fourth bounded fix pass:

- JSON-safe traversal now detects cycles/depth overflow before copying.
- Defensive-copy failures are sanitized without catching process-control
  exceptions.
- Focused M9-D1 suite: `31 passed`; M9/M8 regression: `42 passed`;
  architecture/schema: `37 passed`; compileall and diff-check passed.
