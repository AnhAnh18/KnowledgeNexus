# M10-B Boundary Validation Fix

Address only the confirmed findings in
`.codex-workflow/20260805-m10/19-m10b-review-1.md`.

- Make the M10-B composition boundary use the shared Foundation schema
  validator (injected at the application boundary and available to the pure
  composition function) for all eight non-tombstone streams. Preserve
  sanitized, atomic failures and reject malformed/extra record fields before
  relation, media, ACL, symbol, or sync field access.
- Add explicit M10-B provenance rules: Confluence document/chunk/media records
  must carry the requested page/source version identity; selected pages must
  be ordered and scope-valid; unresolved relations must retain a non-fabricated
  target marker and valid status; sync rows must be schema-valid and match
  source/entity/version identity; Git records must retain exact repository,
  branch, commit, and deny-safe ACL ownership.
- Enforce media count budget, parent ACL inheritance, source/content provenance,
  and allowed processing statuses. Compute `media_processed` and
  `media_failed` from emitted statuses rather than constants.
- Add exact-field and forged-instance validation for `M10CompositionResult`,
  require callable adapter `collect` methods, and strengthen ACL tag/path and
  symbol line provenance checks using the shared contract grammar.
- Update only M10-B source/tests and the M10-A Windows `Path` compatibility
  correction already present in the working tree. Do not add exporter, CLI,
  roadmap/state, connector, network, or real-run behavior.

Required adversarial tests cover object/None/wrong containers, missing and
forbidden fields, forged models, invalid schemas, page/source-version drift,
unresolved Jira targets, ACL inheritance gaps, media budget/status/provenance,
symbol path/line drift, sync mismatches, duplicate IDs, adapter exceptions,
non-callable adapters, zero dependency calls, atomic failure, metrics, and
empty initial tombstones. Re-run focused M10-B/M10-A tests, bounded M9/M6G and
architecture regressions, compileall, and diff-check before a fresh independent
review.
