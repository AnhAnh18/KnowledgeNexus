# M10-B Final Boundary Fix

Address only the four confirmed findings in
`.codex-workflow/20260805-m10/27-m10b-review-final.md`.

- Keep the injected validator seam, but always run the canonical shared
  `FoundationSchemaValidator` against an untouched deep copy in addition to
  the injected validator. A no-op/custom validator must never bypass schema
  shape/runtime validation; validator mutation and arbitrary exceptions fail
  closed without changing the projection.
- Make the application composition boundary sanitize every ordinary
  exception from pure composition as `PROJECTION`, including malformed
  missing-field records; never leak `KeyError`, source data, or exception text.
- Apply the approved relative POSIX path grammar to Git chunks as well as Git
  documents and symbols.
- Reject `unknown` and other fabricated placeholders for every unresolved
  relation status, while retaining explicit Jira targets for
  `mentions_jira_key`.
- Bind source ownership to the originating typed handoff before merged
  projection: Confluence handoffs may contain only Confluence document/chunk/
  ACL/media records and Confluence relations; Git handoffs may contain only
  Git document/chunk/ACL/symbol records and no media/relations. Reject any
  cross-source record before downstream field access.

Add adversarial tests for no-op validator/schema-invalid records, validator
mutation/exception, missing-field sanitization, Git chunk path traversal and
backslash, unknown unresolved targets, cross-handoff ownership drift, zero
partial output, and existing result/metrics/provenance invariants. Run the
focused M10-A/M10-B suite, bounded M9/M6G/architecture regressions,
compileall, and diff-check before fresh independent re-review. Do not touch
M6G/M9 schemas, exporter/CLI, roadmap/state, or real-run behavior.
