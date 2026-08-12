RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M10-A Profile Provenance Fix - Reviewed

The fix is bounded to M10-A models/tests and should use the `build` profile,
but one contract issue must be resolved before implementation: an existing
`OnePageExportProfileBundle` does not retain its normalized profile text
(`InitVar` values are discarded), so its `config_hash` cannot be recomputed
from the bundle alone.

## Required implementation clarification

- Preserve the M6G profile model and loader unchanged. Add an M10-owned trusted
  profile-identity/preimage value at the request boundary (for example, the
  two canonical normalized profile strings or an immutable identity object
  carrying them) and validate its exact fields/types. Recompute the approved
  canonical hash from those bytes and the code-owned constants, then require
  equality with `profile_bundle.config_hash`. Do not accept an arbitrary hash
  or an independently supplied text/object pair; the identity must be produced
  by the approved bundle-loading path and be revalidated before adapters or
  filesystem access.
- Revalidate the exact `OnePageExportProfileBundle` field set and both nested
  `ChunkingProfile`/`JiraRelationProfile` field sets before dereferencing them,
  including forged missing/extra attributes. Re-run their post-init checks and
  fail with sanitized `TypeError`/`ValueError` (never `AttributeError`).
- Bind `M10SnapshotProjection.chunker_version` to the request's exact loaded
  `ChunkingProfile.chunker_version` at the composition boundary. Reject empty,
  malformed, or mismatched projection values before any adapter/dependency
  call; do not add an independent caller-controlled chunker version.

## Required adversarial tests

- Forge the bundle, each nested profile, and the new profile-preimage identity
  with `object.__new__`/`object.__setattr__`; cover missing/extra fields, wrong
  runtime types, forged config hash, non-normalized or tampered profile text,
  and nested profile identity drift. Assert only sanitized typed errors and
  zero adapter/filesystem calls.
- Parameterize projection chunker versions as empty, malformed, wrong active
  version, and exact profile version. Exercise the real request-to-projection
  composition boundary and assert mismatches fail atomically before adapters;
  retain valid profile/hash and deterministic happy-path tests.
- Assert no M8/M9/exporter/CLI/roadmap/state files change. Run the focused
  M10-A test module with an explicit basetemp, `python -m compileall -q src
  tests`, `git diff --check`, and obtain a fresh independent re-review before
  any broader M10 stage.

## Scope decision

After the profile-preimage ownership is made explicit, this remains a
tests-plus-M10-A-model fix only. Do not modify M6G profile classes/loaders,
exporters, CLI, orchestration, or M8/M9 seams.
