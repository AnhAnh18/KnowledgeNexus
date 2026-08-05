# M10-A Independent Re-Review

Review target: current M10-A snapshot after `12-m10a-fix-implementation.md`.
Source and test files were not modified.

## Findings

- **P1 - Profile/config derivation is not revalidated at the M10 boundary.**
  `M10SnapshotRequest.__post_init__` checks that `profile_bundle.config_hash`
  is a lowercase 64-hex string but does not invoke the bundle's derivation
  contract or compare the hash to the normalized embedding/Jira profile
  inputs. A forged `OnePageExportProfileBundle` with valid nested profile
  objects and an arbitrary hash can therefore pass. This violates the plan's
  prohibition on arbitrary caller-supplied config hashes.

- **P1 - Projection accepts an arbitrary/empty chunker version.**
  `M10SnapshotProjection.__post_init__` only checks `chunker_version` is a
  string; `""` and unrelated values are accepted. The approved contract
  requires the loaded `ChunkingProfile.chunker_version`, with no independent
  caller-supplied chunker version.

## Verification

- Focused M10-A tests: `22 passed`.
- M6G compatibility slice: `37 passed`.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed with existing line-ending warning.
- Prior exact-field, strict-RFC3339, result/status, and reparse-point fixes are
  present and covered by the updated adversarial tests.

VERDICT: CHANGES_REQUIRED
