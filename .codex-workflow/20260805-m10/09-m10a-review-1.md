# M10-A Independent Review

Review target: current M10-A snapshot after `08-m10a-implementation.md`,
against `06-plan-approved.md` and `AGENTS.md`. Source and test files were not
modified.

## Findings

- **P1 - Exact-field and forged-instance validation is incomplete across the
  public models.** `M10ConfluenceScope.__post_init__`,
  `M10ConfluenceExclusion.__post_init__`, and `M10MediaPolicy.__post_init__`
  accept forged instances with forbidden `extra` fields (direct probes call
  `__post_init__` successfully). `M10SnapshotMetrics.__post_init__` likewise
  accepts an extra field, while missing fields leak `AttributeError` rather
  than a model validation error. `M10SnapshotRequest`,
  `M10SnapshotProjection`, and `M10QualityReportInput` have no exact-field
  checks and missing/extra forged fields can therefore be accepted or leak
  raw attribute exceptions. This violates the plan's exact immutable fields,
  wrong-runtime-type fail-closed boundary, and forged-instance revalidation
  requirements.

- **P1 - Timestamp validation is not strict RFC3339.** Both
  `M10SnapshotRequest` and `M10SnapshotProjection` only call
  `datetime.fromisoformat`; naive timestamps (`2026-01-01T00:00:00`) and
  date-only values (`2026-01-01`) are accepted, despite the approved plan
  requiring strict RFC3339 timestamps (including timezone). These values can
  cross the snapshot wire-model boundary and produce non-canonical manifest
  metadata.

- **P2 - Dataset-root reparse-point protection is missing.** Request validation
  checks `Path.is_symlink()` but does not reject Windows junctions/other
  reparse points, although the plan explicitly requires a plain directory with
  no symlink/reparse point. The path-safety gate is therefore incomplete on
  Windows.

## Validation

- Focused M10-A tests: `9 passed`.
- Adversarial probes confirmed the exact-field acceptance and timestamp
  acceptance described above.
- No production side-effect calls are present in the reviewed model layer;
  validation is local apart from read-only dataset-root path checks.

VERDICT: CHANGES_REQUIRED
