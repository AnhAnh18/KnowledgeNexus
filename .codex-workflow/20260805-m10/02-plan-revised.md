# M10 First Full POC Foundation Snapshot - Revised Plan

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Goal and gate posture

M10 will add a bounded, multi-source Foundation full-snapshot composition
seam. It will reuse the existing M3 writer/completer/publisher and preserve
the approved M6G one-page contract and golden export unchanged. M8-AC's real
10-20 page gate remains an external acceptance input: it is not required to
start M10 or to produce the synthetic contract proof, but no real-corpus or
real-POC PASS may be claimed without the approved generation, ordered scope,
pinned tokenizer assets, credentials handling, and sanitized aggregate report.

The initial snapshot has exactly ten files in its version directory (eight
JSONL streams, `manifest.json`, `quality_report.md`); `LATEST.txt` is a
separate dataset-root pointer. Initial `tombstones.jsonl` is empty unless an
explicit normative exception is approved. Real deletion/delta behavior is a
precondition only for the second sync or first delta export.

## Contract decision (M10-A)

Add a new additive M10 POC contract/model layer rather than widening the M6G
one-page public models in place:

- `M10SnapshotRequest` binds an exact crawl run/generation, approved
  Confluence scope/exclusions and ordered page selection, raw-generation
  provenance, restriction/attachment observation provenance, pinned Git
  repository/branch/commit, media policy, normalized profile bundle/config
  identity, `generated_at`, dataset root, and explicit `full_snapshot` mode.
- `M10SnapshotProjection` owns immutable copies of the eight streams, source
  scopes, profile/config identity, and metrics. It enforces exact fields,
  schema-valid records, deterministic stream ordering, graph/count invariants,
  and sanitized failure categories.
- `M10SnapshotResult` binds staging/publication status, dataset version,
  counts, digest, and error category with impossible-combination checks.
- A dedicated `M10QualityReportInput` and generic quality-report renderer
  support populated media/symbol/sync streams while leaving the existing
  `one_page_quality` completer path and its deferred-stream assumptions intact.

All public models revalidate forged frozen instances and reject `None`,
`object()`, wrong containers/types/enums, missing/extra fields, unsafe roots,
secrets/raw-content fields, invalid paths/timestamps/provenance, and impossible
counters before dependency calls or filesystem side effects. Config hash is
derived only from the approved normalized profile bytes and code-owned policy;
callers cannot provide an arbitrary hash or second profile identity.

## Trusted composition seams (M10-B)

Create injected adapter protocols and bounded application composition, with
no direct connector or exporter internals:

1. **Confluence adapter:** consume M7 raw generation envelopes and M8-D page
   set processing; enforce run/generation/source-version/page ordering, raw
   provenance, scope/exclusion policy, M8-E summary identity, ACL materialized
   records, Jira relation records, and M9-A media outputs. Fail atomically on
   any page or dependency result; do not reinterpret M8/M9 policy.
2. **Git adapter:** consume M9-B/M9-C authority observations over the pinned
   repository/branch/commit; enforce POSIX path containment, exclusions,
   commit-bound bytes/spans, deterministic ordering, and deny-safe ACL tags.
3. **Cross-source graph validator:** enforce document/chunk identity and
   source ownership, ACL/document cardinality, non-empty deny-safe chunk ACL,
   relation source/target policy (external Jira targets must carry explicit
   unresolved status), media parent/ACL inheritance, symbol-to-chunk linkage,
   and sync/tombstone entity/version consistency. Invalid references are
   explicit failures or quarantined only through a typed contract; never silent
   drops or fabricated evidence.

The composition result remains in memory until the M3 staging writer begins.
No Qdrant, embedding, retrieval, chat, checkpoint, or unapproved raw-store
side effects are introduced.

## Generic export boundary (M10-C/D)

- Extend `FullSnapshotStagingCompleter` additively with a generic quality input
  and report mode; preserve old call signatures, one-page report bytes, file
  set checks, cleanup, and golden fixture behavior.
- Reuse `FullSnapshotStagingWriter`, `FullSnapshotStagingCompleter`,
  `FullSnapshotPublisher`, and `DatasetVersionGenerator`; do not add a second
  writer/completer/publisher.
- Add one M10 application/CLI boundary that accepts sanitized configuration and
  injected adapters, preserves existing CLI exit mappings 1-13 and reserved
  M6G categories 14-19, and introduces only typed M10 categories for adapter,
  projection, staging, completion, publication, and post-publication failures.
- Enforce output-root containment, no symlinks/reparse points, no-clobber and
  failed-run atomicity, exact dataset-version/folder/manifest/LATEST equality,
  ten-file version layout, and no secret/path/content/ID/hash leakage in
  reports or stderr.

## Synthetic acceptance and external gate (M10-E)

Synthetic fixtures must include non-empty Confluence and Git streams, media
and symbols where policy permits, explicit empty initial tombstones, and
diagnostic sync state. Run twice over immutable inputs and compare canonical
stream bytes, manifest, quality report, counts, and publication behavior.
Negative tests must cover malformed adapter results, identity drift, unresolved
relations/symbols, ACL gaps, duplicate/collision IDs, validator mutation,
count mismatch, unsafe/pre-existing paths, symlinks/reparse points,
publication/completion failure, corrupted `LATEST.txt`, and unchanged prior
pointer after failure.

The real M10 run is a separate operator gate. It requires approved Confluence
scope/generation and raw provenance, pinned Git commit, tokenizer/assets,
credential handling outside Git/evidence, and a sanitized aggregate report.
Until supplied, roadmap/state must say `pending_external_input` rather than
claiming a real full-snapshot PASS.

## Validation and review sequence

1. Implement only the approved M10-A/B/C/D/E bounded slice.
2. Run focused M10 tests, affected M3/M6G/M7/M8/M9 regressions,
   architecture checks, `python -m compileall -q src tests`, and scoped
   `git diff --check`.
3. Obtain a fresh independent review in a new session; address every confirmed
   P0-P3 finding with a bounded fix plan/review and revalidation.
4. Update `.local_ai/ROADMAP.md` and `.local_ai/IMPLEMENTATION_STATE.md` only
   after review approval, recording the external real-run gate explicitly.
5. Stage only intended files, commit, and push `codex/m8-m9`.

## Non-goals

No Indexing/Qdrant import, embedding, retrieval, chat, UI, 100k optimization,
delta export, M8/M9 contract redesign, or fabricated real operator evidence.
