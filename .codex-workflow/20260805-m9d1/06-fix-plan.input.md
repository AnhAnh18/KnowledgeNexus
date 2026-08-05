# M9-D1 Bounded Fix Plan

Address only the four confirmed findings from the fresh independent review.

1. Make `TombstoneRecordBuilder` detect any validator mutation or field-set
   drift after validation and fail closed.
2. Make `TombstoneProjectionResult` validate the exact tombstone record shape,
   required/optional keys, enum values, IDs, schema version, and success root
   metrics; keep failure payloads empty.
3. Make model `__post_init__` methods use sentinel-safe attribute reads so
   forged frozen instances fail with `TypeError`/`ValueError`; the use case
   maps forged requests to `invalid_request`.
4. Remove implicit filesystem schema loading from `ProjectTombstones` by
   requiring an injected validator dependency; update focused callers/tests
   without wiring this seam into exporters.

Acceptance: focused adversarial tests cover mutating validators, malformed
record shapes, forged objects, and missing dependencies; prior M9-D1,
M9-A/B/C, M8-D/E, architecture, compileall, and diff-check regressions pass.
No exporter, store, checkpoint, network, or roadmap behavior changes.
