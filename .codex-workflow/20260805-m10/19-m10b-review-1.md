# M10-B Independent Review

Review target: current uncommitted M10-B composition implementation, including
`m10_composition.py`, `compose_m10_snapshot.py`, exports, and the M10-A path
diff, against `06-plan-approved.md`, M9 schemas, and `AGENTS.md`. Source and
test files were not modified.

## Findings

- **P1 - Cross-stream records are not schema-validated or fully shape-
  validated.** Composition accepts arbitrary record dictionaries and checks
  only a small subset of fields. A relation with
  `resolution_status="unresolved_target"` and no target metadata is accepted;
  an active sync record containing only `entity_id` and `status` is accepted;
  and a Confluence document outside `ordered_page_ids`/scope with no source
  version or page provenance is accepted. This violates the required M9
  schema validation, selected-page/source-version consistency, unresolved Jira
  target policy, and sanitized typed handoff boundary.

- **P1 - Media policy and ACL inheritance are incomplete.** `max_assets` is
  never enforced, and media records are not required to carry inherited ACL
  tags or raw/content provenance tied to their parent. A probe with policy
  `max_assets=0` and one `not_processed` media record (with only parent ID and
  source version) composes successfully. This breaches the deny-safe media
  parent/ACL/provenance requirements.

- **P1 - Composition metrics undercount media processing.**
  `media_processed` and `media_failed` are hard-coded to zero regardless of
  emitted media statuses, so successful projections report incorrect metrics
  whenever parsed/OCR/summarized/failed assets exist.

- **P1 - `M10CompositionResult` lacks exact-field forged-instance guards.** Its
  dataclass `__post_init__` validates combinations but does not reject missing
  or forbidden fields, allowing a forged result object to cross the application
  boundary without the required runtime shape validation.

- **P2 - Adapter constructor accepts non-callable `collect` attributes.**
  `ComposeM10Snapshot.__init__` uses `hasattr` rather than checking that
  `collect` is callable, so malformed adapters are accepted until execution.

- **P2 - Symbol and ACL field validation is incomplete.** Symbol file paths are
  only checked non-empty (not approved POSIX/line provenance grammar), and ACL
  records are checked for a non-empty list but not schema-valid tags, source
  ownership, or inheritance consistency.

## Validation

- Focused M10-B model/use-case tests: `12 passed`.
- Architecture suite: `88 passed`.
- M9 bounded regression: `116 passed`.
- M6G compatibility/golden slice: `37 passed`.
- Adversarial probes confirmed acceptance of over-limit media, missing media
  ACL/provenance, unresolved relation target omission, incomplete sync state,
  and out-of-scope Confluence documents.

VERDICT: CHANGES_REQUIRED
