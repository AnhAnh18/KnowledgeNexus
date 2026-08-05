# M10-A Profile Provenance Fix

Address only the two P1 findings in `13-m10a-review-2.md`.

- Revalidate `OnePageExportProfileBundle` at the M10 request boundary,
  including exact nested `ChunkingProfile`/`JiraRelationProfile` fields and
  recomputation of `config_hash` from the bundle's canonical normalized profile
  inputs. A forged bundle with an arbitrary hash must fail closed before any
  adapter or filesystem dependency call.
- Bind `M10SnapshotProjection.chunker_version` to the loaded request/profile
  identity (`ChunkingProfile.chunker_version`) rather than accepting an
  arbitrary or empty caller value. Reject forged profile/projection instances
  and mismatched chunker versions.
- Add focused adversarial tests for forged profile hash, missing/extra profile
  fields, wrong profile types, empty/mismatched projection chunker version, and
  zero dependency calls. Keep production scope limited to M10-A models/tests;
  do not modify exporter, CLI, orchestration, roadmap, or state.
