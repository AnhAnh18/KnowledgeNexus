# M10 First Full POC Foundation Snapshot

## Objective

Build the bounded Foundation-side composition/orchestration needed to produce
the first contract-valid `full_snapshot` for an approved Confluence scope and
configured local Git branch. Reuse the existing M3 staging, completion, and
publication APIs; do not create a parallel exporter. M8-AC's real mini-corpus
report is useful acceptance evidence but is not a prerequisite for starting
M10 or for the initial full snapshot. Real delta/deletion behavior remains
required before a second sync or first delta export, not before this initial
snapshot.

## Stages

### M10-A - Approved run input and snapshot envelope

- Define immutable, runtime-validated input/result/metrics models for one
  generation-bound POC run: Confluence generation/scope/exclusions, raw-page
  provenance, restriction/attachment observations, approved Git repository/
  branch/commit, media policy, generated-at, dataset root, and profile/config
  identity.
- Require exact field sets, approved enum/status combinations, canonical source
  identities, non-empty scope, bounded paths/budgets, timezone-aware timestamp,
  and no secrets or raw-content leakage.
- Fail closed on `None`, `object()`, wrong containers/types/enums, missing or
  extra fields, forged frozen objects, invalid provenance, and impossible
  counters before any I/O or dependency calls.

### M10-B - Confluence and Git bounded composition

- Compose M7 raw-generation/page selection with M8-D page-set processing,
  M8-E summaries, existing ACL materialization, Jira relation mapping, and
  M9-A media policy/processing seams for the approved Confluence scope.
- Compose M9-B Git code documents and M9-C symbols over the pinned local
  repository commit/branch; preserve exact commit/path/line provenance and
  deterministic fallback behavior.
- Keep source ownership and generation identity bound across all records;
  produce all-or-nothing in-memory stream projections with no partial export.
- Do not add embedding, Qdrant, retrieval, chat, raw-store mutation beyond
  explicitly approved input seams, or network behavior outside injected ports.

### M10-C - Cross-stream graph and export projection

- Aggregate `documents`, `chunks`, `relations`, `acl`, `media_assets`,
  `symbols`, `sync_state`, and `tombstones` deterministically.
- Enforce schema validation for every record, non-empty deny-safe `acl_tags`
  on every chunk, document/chunk identity binding, relation source/target
  resolution policy, media parent/ACL inheritance, symbol-to-chunk resolution,
  and sync/tombstone entity/version consistency.
- Require empty tombstones for the initial `full_snapshot` unless an explicit
  contract exception is approved; no fabricated deletion evidence.
- Validate exact stream counts and cross-field metrics, then adapt the trusted
  projection to existing `FullSnapshotStagingWriter`,
  `FullSnapshotStagingCompleter`, and `FullSnapshotPublisher`.

### M10-D - CLI/run boundary and deterministic publication

- Add one bounded application/CLI orchestration boundary that accepts only
  sanitized configuration and injected source adapters, stages atomically,
  completes the quality report, publishes the version directory, and updates
  `LATEST.txt` only after all contract checks pass.
- Enforce no-clobber/failed-run atomicity, explicit `full_snapshot` mode,
  manifest/count/folder handshake, output-root containment, no symlinks or
  unexpected files, no secrets in logs/reports, and deterministic reruns.

### M10-E - Acceptance and closeout

- Add synthetic/fixture-backed end-to-end acceptance for all ten published
  artifacts and a negative matrix for malformed streams, identity drift,
  ACL gaps, unresolved relations/symbols, count mismatches, publication
  failures, forbidden side effects, and secret leakage.
- Run relevant M8/M9/export regressions, architecture tests, compileall, and
  scoped diff checks.
- After implementation, obtain a fresh independent review in a new session;
  fix every confirmed P0-P3 finding in scope, then update roadmap/state and
  commit/push.
- Treat the real Confluence/Git full POC invocation as an external acceptance
  gate requiring operator-approved scope, generation, credentials/assets, and
  sanitized aggregate evidence; never fabricate a real PASS.

## Non-goals

- No Indexing/Qdrant embedding/import, retrieval, chat, Gauss, or UI work.
- No redesign of M8/M9 contracts or existing M3 writer/completer/publisher.
- No broad performance/100k scale work and no delta export implementation in
  the initial snapshot stage.

## Acceptance

The bounded implementation is complete only when synthetic/fixture-backed
validation proves schema-valid deterministic output for all ten expected files,
correct counts and `LATEST.txt`, provenance/ACL/relation/media/symbol graph
invariants, atomic failure behavior, and no forbidden side effects; an
independent review is `PASS`; roadmap/state record any remaining external gate;
and the approved changes are committed and pushed.
