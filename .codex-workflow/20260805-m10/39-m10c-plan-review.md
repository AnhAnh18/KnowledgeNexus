RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-C Plan Review

The plan is correctly scoped to an additive completer API and explicitly
protects the existing M6G one-page behavior, but several contracts need to be
made precise before implementation.

## Required Clarifications

- Define the exact `complete` signature and mode precedence. Validate
  `m10_quality` and `one_page_quality` runtime types, mutual exclusion, and
  validator type before any `exists`, directory, report, or staging mutation;
  preserve old `one_page_quality=None|OnePageExportQualityReportInput` bytes and
  exception/no-clobber behavior byte-for-byte.
- Make schema validation authoritative and ordering explicit: strict JSONL and
  manifest readback (duplicate-key/non-finite rejection) first, then validate
  untouched deep copies with the shared validator before count or field access.
  Detect validator mutation/exception and ensure report rendering uses a
  separate defensive copy; no malformed record may reach report generation.
- Specify all generic invariants: exact eight manifest count keys and integer
  values, exact on-disk counts, exact `M10QualityReportInput.expected_counts`,
  `tombstones.jsonl` empty, and media/symbol/sync streams allowed non-empty.
  Require manifest `source_scopes` to be schema-valid, deterministically keyed,
  and equal to the typed quality input source scopes (with a defined canonical
  representation), not merely present.
- Define the deterministic report schema in the plan: exact section order from
  the approved M10 quality contract (`Snapshot`, `Active Profiles`, `Record
  Counts`, `Jira Relation Quality`, `ACL Quality`, `Media Quality`, `Symbol
  Quality`, `Sync State`, `Tombstones`, `Completion Checks`, `Publication
  State`, `Scope`), exact key order, scalar types/formatting, and required
  `PENDING_AT_REPORT_COMPLETION` markers. Reject or sanitize arbitrary metric
  dict values so paths, IDs, URLs, principals, hashes, exception text, secrets,
  record text, and raw content can never enter the report.
- Define quality-input mutation detection and exact-field/forged-instance
  handling at the boundary, including nested dict/list values and wrong runtime
  containers. Report rendering must be pure and deterministic across repeated
  runs.
- Preserve existing completer cleanup/no-clobber/race behavior: all generic
  validation must finish before creating `quality_report.md`; any write or
  final file-set failure removes only the owned report and leaves staging
  streams unchanged. Do not derive versions or touch `LATEST.txt`.

## Acceptance and Scope

Add tests for both quality modes, wrong types, mutual exclusion, strict parser
duplicates/NaN, schema-invalid and validator mutation/exception cases, count
drift, source-scope drift, non-empty media/symbol/sync acceptance, non-empty
tombstones rejection, unsafe/pre-existing report paths, cleanup, deterministic
report bytes, and all existing M6G golden/one-page tests. Keep changes limited
to the completer, generic report helpers/models/tests, and additive exports;
do not alter M6G models/CLI, writers, publishers, connectors, network, raw or
checkpoint stores, or dataset-version/LATEST behavior.

VERDICT: CHANGES_REQUIRED
