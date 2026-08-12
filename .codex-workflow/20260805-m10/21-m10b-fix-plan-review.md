RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-B Fix Plan Review

The proposed fix plan addresses all confirmed findings in
`19-m10b-review-1.md`, but the implementation contract needs the following
precision before coding.

## Required Clarifications

- Define the injected Foundation schema-validator protocol and exact schema
  names for all eight streams. `compose_m10_projection` must receive the
  validator explicitly (and the application use case must require a callable
  validator), validate exact record fields before any `.get`/field access, and
  defensively copy records after validation so validator mutation cannot alter
  the projection.
- Enumerate provenance keys and equality rules per source/stream. Confluence
  documents, chunks, and media must bind to `request.ordered_page_ids`, the
  requested source version, and the selected scope; Git records must bind
  repository/branch/commit and have exactly deny-safe repo ACL ownership.
  State how records without a page/file identity are rejected.
- Specify unresolved Jira relation requirements by status. In particular,
  `unresolved_target` must carry an explicit non-fabricated target marker and
  every other unresolved status must satisfy its corresponding schema shape;
  resolved relations must not carry contradictory unresolved markers.
- Specify sync-state identity fields (schema version, source, entity, source
  version, status), uniqueness/cardinality, and the empty-stream rule. Reject
  `error`/`tombstoned` rows and any row whose identity/version does not match
  an emitted selected entity.
- Specify media ACL inheritance and provenance fields, including the behavior
  when `include_attachments` is false, `allowed_processing_statuses` is empty,
  and `max_assets` is exceeded. Define processed counting (`parsed|ocr|
  summarized`) versus failed/not-processed counting and require parent ACL
  equality or an explicit safe superset rule.
- Define the approved symbol file-path grammar and line-span constraints, and
  require exact repo/branch/commit/file identity for every Git symbol. Clarify
  whether non-Git symbols are allowed and their provenance contract.
- Define exact fields and failure combinations for `M10CompositionResult`,
  including forged missing/extra fields, wrong runtime values, and sanitized
  exception behavior. Preserve the existing one-page/M6G models unchanged.

## Risks and Scope

- Schema-validator calls can mutate records or raise arbitrary exceptions;
  tests must prove fail-closed `PROJECTION`/`ADAPTER` results, no leaked text,
  no partial projection, and no output/filesystem calls.
- Validation ordering is security-sensitive: wrong runtime types, handoff
  exact fields, and schema shape must fail before relation/media/ACL/symbol/
  sync field access. Invalid request objects must call neither adapter;
  malformed handoffs must not invoke downstream dependencies.
- Keep the change limited to M10-B models/use case/tests plus the explicitly
  approved M10-A Windows `Path` compatibility correction; do not alter M9/M6G
  schemas, exporters, CLI, roadmap/state, connectors, or real-run behavior.

## Acceptance Tests

- Parametrize `object()`, `None`, wrong containers, missing/extra/forged fields,
  schema-invalid records, validator mutation/exception, and wrong adapter
  runtime types. Assert sanitized categories, zero adapter calls where
  applicable, empty/atomic failure output, and no leaked exception text.
- Cover Confluence page ordering/scope/source-version drift; Git identity and
  ACL gaps; duplicate IDs; inherited ACL mismatch; media parent, raw/content
  provenance, status, attachment policy, and budget; relation statuses and
  unresolved target markers; symbol path/provenance/line drift; sync identity,
  status, version, duplicate, and empty-stream behavior; and empty tombstones.
- Assert deterministic stream ordering, exact stream counts, source document
  counts, unresolved relation count, media processed/failed counts, and
  `tombstones == ()`.
- Run focused M10-A/M10-B tests, bounded M9 and M6G compatibility/golden
  suites, architecture tests, `python -m compileall -q src tests`, and
  `git diff --check`; then obtain a fresh independent review before any
  roadmap/state update.

VERDICT: CHANGES_REQUIRED
