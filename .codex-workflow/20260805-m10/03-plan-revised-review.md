RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10 Revised Plan Review

The revision resolves the major architectural blockers and is directionally
ready, but it still needs a few contract-level clarifications before
implementation is authorized. Keep the `complex` profile: this remains a
multi-boundary composition and publication change, not a local build task.

## Confirmed corrections

- M6G remains unchanged: the plan adds M10 models and a generic completion
  mode instead of widening the one-page models, and explicitly preserves the
  existing report bytes, file checks, cleanup, and golden export.
- The artifact count is correct: exactly ten files inside the published version
  directory (eight JSONL streams, `manifest.json`, `quality_report.md`), with
  `LATEST.txt` counted separately at the dataset root.
- The M8-AC real gate is correctly external and remains
  `pending_external_input`; synthetic proof is not presented as a real-corpus
  or real-POC PASS.
- The plan includes typed adapter seams, graph validation, no partial output,
  adversarial input classes, publication-failure atomicity, deterministic
  reruns, independent review, and staged roadmap/state updates.

## Required final clarifications

1. Lock the M10 wire contract before coding. State exact constants and shapes
   inherited from M6G/M3 (`dataset_name`, source IDs, `export_mode`,
   `schemas_version`, manifest `source_scopes`, eight exact count keys), and
   identify any new M10 source-scope representation. Define exact field sets,
   enum values, result/status combinations, and failure categories for
   `M10SnapshotRequest`, `M10SnapshotProjection`, `M10SnapshotResult`, and
   `M10QualityReportInput`; typed construction must reject impossible
   combinations and forged/missing/extra fields.

2. Make profile/config derivation executable rather than descriptive. Reuse
   the M6G canonical JSON inputs, normalization-policy identity, strict UTF-8
   profile bytes, loaded profile/chunker version, and lowercase SHA-256 rules.
   The plan must state that `chunker_version` comes from the loaded embedding
   profile and equals every emitted chunk, and that `generated_at` is preserved
   exactly in the manifest while `DatasetVersionGenerator` derives the folder
   and `LATEST.txt` value. No arbitrary config hash or independently loaded
   profile text/object is allowed.

3. Define stream semantics for the new generic completion mode. The synthetic
   plan mentions populated media/symbol streams and diagnostic sync state but
   only says initial tombstones are empty. Specify whether `sync_state` may be
   populated, its exact schema/version consistency rules, and the required
   empty/non-empty policy for media, symbols, sync state, and tombstones. The
   generic report must have a locked deterministic section/field order and
   must never claim post-publication checks before publication; add a test that
   the existing M6G one-page report remains byte-identical.

4. Complete adapter contracts and ACL policy. For every Confluence/Git/media/
   symbol/relation handoff, name the exact trusted result type, provenance
   fields, ordering, sanitized error mapping, and all-or-nothing behavior.
   Explicitly define how Git chunks obtain non-empty deny-safe `acl_tags` and
   how external Jira relations with `resolution_status` unresolved are
   represented without inventing targets. Wrong runtime types must fail before
   field access or side effects.

5. Close the CLI/path contract. Enumerate the closed M10 category vocabulary
   and map each to an existing reserved exit code (or obtain approval for new
   codes); preserve M6G exit mappings 1-19 and structured configuration stderr.
   Specify dataset-root derivation, plain-directory/symlink/reparse checks,
   staging/final no-clobber behavior, prior `LATEST.txt` preservation, and
   sanitized stdout/stderr fields. Do not accept a caller-supplied dataset
   subdirectory that bypasses the M6G containment rules.

6. Split the implementation into independently reviewable gates: (a) models
   and trusted composition, (b) pure cross-stream projection, (c) additive
   generic completion and M3 publication, (d) CLI boundary, and (e) synthetic
   acceptance. Each gate must have its own focused tests and must not perform
   the real operator run or update roadmap/state before final independent PASS.

## Required adversarial and regression tests

- Exercise `object()`, `None`, wrong containers/types/enums, missing/extra
  fields, forged frozen objects, invalid paths/provenance/timestamps, secrets
  or raw-content injection, and impossible counters at every public model and
  application boundary. Assert sanitized failure category, no dependency
  calls, and zero partial records/files.
- Use fixtures with both Confluence and Git documents, non-empty media/symbol
  streams where policy permits, explicitly specified sync/tombstone behavior,
  relation resolution/unresolved cases, ACL inheritance, duplicate/collision
  IDs, validator mutation, and source/profile/config drift.
- Verify exactly ten files in the version directory, eight manifest count keys,
  schema validation and byte-level deterministic stream/report output, exact
  manifest/directory/LATEST equality, no symlinks/unexpected files, failed-run
  atomicity, publication/completion failure cleanup, and unchanged prior
  pointer. Test M6G one-page golden output through the generic completer path.

## Acceptance commands

The final revised plan must name the exact focused commands and basetemp paths,
not only the phrase "run regressions." At minimum run the M10 model/composition,
projection/completion, CLI/publication, and architecture suites, then the
affected M3/M6G/M7/M8/M9 regressions, for example:

`$env:PYTHONPATH='src'; python -m pytest -q tests/foundation --basetemp=.codex-workflow/20260805-m10/pytest-m10-foundation`

`$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10-arch`; `python -m compileall -q src tests`; `git diff --check`

Use the repository's bounded M7/M8/M9 regression selections with explicit
basetemps and record exact results. Obtain a fresh independent review in a new
session before roadmap/state update, staging, commit, or push.
