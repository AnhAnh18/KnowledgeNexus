RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10 Final Plan Review

The final plan resolves the major M6G compatibility, populated-stream,
artifact-count, external-gate, and security concerns. It is suitable for a
complex implementation only after the remaining contract omissions below are
closed; this is a conditional approval, not authorization to improvise during
implementation.

## Confirmed requirements

- M6G one-page models, CLI behavior, deferred-stream semantics, report bytes,
  and golden output remain unchanged. M10 uses an additive generic completion
  path and does not create a parallel writer/publisher or import private CLI
  state.
- The version directory count is exactly ten files: eight JSONL streams,
  `manifest.json`, and `quality_report.md`. `LATEST.txt` is a separate
  dataset-root pointer, with manifest counts limited to the eight stream keys.
- M8-AC remains `pending_external_input`; synthetic tests cannot be presented
  as the real full-POC gate. Tombstones are explicitly empty for the initial
  full snapshot.
- The plan specifies profile/config derivation, populated-stream graph rules,
  Git ACL handling, sanitized CLI output, no-clobber/path checks, adversarial
  tests, explicit focused commands, and fresh independent review before
  roadmap/state or Git updates.

## Blockers to close before implementation

1. **Complete exact model contracts.** The plan lists fields but does not give
   the runtime types/grammars for `confluence_scope`, exclusions, page IDs,
   `media_policy`, and `profile_bundle`, nor the exact aggregate metric fields
   and cross-field invariants. Define these, plus exact field sets and
   missing/extra-field behavior, in the revised contract. For
   `M10SnapshotResult`, specify the allowed fields for each status:
   `composed`, `staged`, `published`, and `failed` (including when counts,
   digest, `dataset_version`, `final_path`, and `failure_category` are present
   or forbidden). Include `export_mode` in the wire projection or explicitly
   state why it is a code-owned constant rather than a model field.

2. **Close the error mapping.** The failure vocabulary includes `invalid_request`
   and `adapter`, but M10-D maps only projection/staging/completion/publication/
   acceptance to exit codes. State the exact mapping for every category,
   preserve the M6G structured configuration stderr shape, and ensure malformed
   dependencies fail closed before adapter/projector or filesystem side
   effects.

3. **Specify sync/report semantics.** The synthetic fixture intentionally emits
   diagnostic `sync_state`, while the initial tombstone stream is empty. State
   the exact allowed sync-state cardinality/status/version policy and whether
   any media/symbol stream may be empty or populated under each media policy.
   Lock the generic quality-report fields, section order, deterministic
   rendering, and pre-publication `PENDING_AT_REPORT_COMPLETION` wording. The
   existing M6G path must continue using the actual
   `OnePageExportQualityReportInput` API and remain byte-identical.

4. **Make adapter provenance executable.** Name the exact trusted result types,
   source/run/generation/version fields, ordering rules, sanitized category
   mapping, and rollback behavior for each Confluence, Git, media, symbol, and
   relation handoff. Define the accepted `repo:<repository>` grammar and the
   `restricted:unresolved` fallback as a closed ACL policy, and require
   source-version/commit/path/line binding before record projection. Define
   how an unresolved Jira relation is represented and counted without a
   fabricated target or silent drop.

5. **Make publication acceptance explicit.** In addition to staging checks,
   require post-publication readback of all ten files, schema/count equality,
   manifest/directory/LATEST equality, unchanged quality-report bytes, and
   prior-pointer preservation after any failure. State exact dataset-root
   derivation and containment so a caller cannot bypass the M6G path policy.

6. **Name all regression commands.** The focused commands are explicit, but
   the bounded M3/M6G, M7, M8-D/E, and M9-A/B/C/D regressions still need the
   concrete test paths and basetemp directories in the implementation plan.
   Implementers must report exact commands and results; no broad unscoped
   suite or real operator invocation belongs in the synthetic gate.

## Acceptance gate

After those clarifications, acceptance requires the listed M10 model/use-case,
exporter, and architecture commands; exact bounded upstream regressions;
`compileall`; `git diff --check`; a fresh independent review with `VERDICT:
PASS`; and only then roadmap/state update, staging, commit, and push. Real
operator evidence remains sanitized aggregate data outside Git and cannot be
claimed until the external inputs exist.
