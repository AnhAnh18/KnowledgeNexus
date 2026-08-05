# M10 First Full POC Foundation Snapshot - Final Approved Plan

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Scope and compatibility

Implement a new additive M10 multi-source snapshot seam. Preserve the existing
M6G one-page models, CLI, quality-report bytes, and golden fixture unchanged;
M10 must not widen `OnePageExportProjection` or its deferred-stream semantics.
M10 may reuse the generic M3 writer/publisher and adds a separate generic
completion/report input path only where needed for populated streams.

M8-AC remains `pending_external_input`: its real 10-20 page result is not
needed to start M10 or to prove synthetic contract behavior, but no real M10
POC PASS may be claimed without approved generation/scope, pinned tokenizer
assets, credentials handled outside Git/evidence, and a sanitized aggregate
report. Tombstones are empty for the initial `full_snapshot`; M9-D behavior is
required before a second sync or first delta export.

## M10-A - Wire contract and trusted inputs

Add exact runtime-validated immutable models with these fields and policies:

- `M10SnapshotRequest`: `run_id`, `generation_id`, `confluence_scope`,
  `confluence_exclusions`, `ordered_page_ids`, `raw_generation_id`,
  `git_repository`, `git_branch`, `git_commit`, `media_policy`,
  `profile_bundle`, `generated_at`, `dataset_root`, `export_mode`.
  `run_id == generation_id`; `export_mode == "full_snapshot"`; page IDs are
  unique, ordered, and scope-valid; Git commit is a 40-lowercase-hex SHA;
  `generated_at` is strict RFC3339; dataset root is absolute, existing,
  non-symlink/reparse, and contains no secrets/raw content in the model.
- `M10SnapshotProjection`: `dataset_name`, `schemas_version`, `source_scopes`,
  `generated_at`, `config_hash`, `chunker_version`, the eight ordered stream
  tuples (`documents`, `chunks`, `relations`, `acl`, `media_assets`, `symbols`,
  `sync_state`, `tombstones`), and typed aggregate metrics. The inherited wire
  constants are `dataset_name="spen_knowledge_poc"`, `export_mode` is fixed to
  `full_snapshot`, `schemas_version="1.0"`, and the manifest has exactly the
  eight count keys. `source_scopes` is canonicalized as sorted `confluence`
  and optional `git` objects containing only approved IDs/space/page or
  repo/branch/commit fields.
- `M10SnapshotResult`: `status` in `composed|staged|published|failed`, optional
  `dataset_version`/`final_path` only for successful states, typed
  `failure_category` in `invalid_request|adapter|projection|staging|
  completion|publication|acceptance`, counts/digest only when consistent.
  Impossible status/field combinations fail closed.
- `M10QualityReportInput`: exact deterministic fields for profile identity,
  eight counts, source-quality observations, ACL/relation/media/symbol checks,
  completion checks, publication state (`PENDING_AT_REPORT_COMPLETION` before
  publication), and source scopes; field/section order is fixed and it never
  carries record text or secrets.

Profile/config derivation reuses the approved M6G normalized embedding/Jira
profile bytes, `ONE_PAGE_NORMALIZATION_POLICY_ID`, `OnePageExportProfileBundle`,
lowercase SHA-256 config hash, and loaded `ChunkingProfile.chunker_version`.
Every emitted chunk must carry that chunker version. `generated_at` is preserved
exactly in the manifest; `DatasetVersionGenerator` alone derives the dataset
version, folder name, and `LATEST.txt` value.

Every public boundary has adversarial tests for `None`, `object()`, wrong
containers/types/enums, missing/extra fields, forged frozen objects, invalid
paths/provenance/timestamps, secret/raw-content injection, impossible counters,
and zero dependency calls before failure.

## M10-B - Trusted source composition

Use injected, typed adapters and all-or-nothing composition:

- Confluence consumes M7 raw-generation envelopes and M8-D/E page-set output;
  validates generation/source-version/page order, ACL materialization, Jira
  relations, attachment observations, and M9-A media results without
  reinterpreting their policies.
- Git consumes M9-B/M9-C commit-bound observations; enforces path exclusions,
  deterministic ordering, and `acl_tags=["repo:<repository>"]` (or an explicit
  deny-safe `restricted:unresolved` result) for every Git document/chunk.
- Media records require existing parent documents and inherited deny-safe ACL;
  symbols require exact repo/branch/commit/file/line provenance and resolve to
  an emitted chunk when `chunk_id` is non-null.
- Relations retain external Jira targets only with explicit unresolved status;
  no fabricated target IDs. Sync state is diagnostic only: each record is
  schema-valid, source/entity/version-consistent, and initial-run statuses are
  `active` (source errors fail the run). Tombstones must be exactly empty.

## M10-C - Cross-stream projection and generic completion

- Validate every record against its schema and enforce document/chunk/ACL
  identity, non-empty ACL tags, relation source/target policy, media parent,
  symbol linkage, sync consistency, deterministic ordering, exact counts, and
  no collisions.
- Extend `FullSnapshotStagingCompleter.complete` additively with a generic
  quality input/report mode; old `one_page_quality=None|OnePageExportQualityInput`
  behavior, report bytes, cleanup, and golden output remain byte-identical.
- Use existing `FullSnapshotStagingWriter` and `ManifestRecordBuilder`; no
  parallel writer or private M6G CLI state.

## M10-D - CLI/publication boundary

- Add one M10 application/CLI entry point over sanitized config and injected
  adapters. Preserve M6G exit mappings 1-19; map M10 failures to existing
  reserved export codes (projection 15, staging 16, completion 17,
  publication 18, acceptance 19) and keep configuration failures in the
  existing structured vocabulary.
- Enforce output-root containment, plain directory/no symlink or reparse,
  staging/final no-clobber, prior `LATEST.txt` preservation on failure, exact
  ten-file version layout, and sanitized stdout/stderr with no paths, IDs,
  URLs, principals, content, hashes, or exception text.

## M10-E - Validation, independent review, and external gate

Synthetic fixtures include non-empty Confluence and Git, media/symbol records,
diagnostic sync state, and empty initial tombstones. Run twice and compare
canonical stream bytes, manifest, report, counts, and pointer behavior. Cover
malformed adapters, identity drift, unresolved references, ACL gaps,
duplicates, validator mutation, unsafe paths, symlinks, publication failures,
LATEST corruption, and atomic rollback.

Validation commands (explicit basetemps):

```text
python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/application/use_cases/test_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-models
python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py tests/foundation/infrastructure/exporters/test_one_page_full_snapshot_exporter.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-export
python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10-arch
python -m compileall -q src tests
git diff --check
```

Also rerun the bounded M3/M6G, M7 raw-generation, M8-D/E, and M9-A/B/C/D
regressions with explicit basetemps. Only after a fresh independent review
`PASS` may roadmap/state be updated and changes committed/pushed. The real
operator full-POC invocation remains an aggregate-only external gate and must
not be represented as complete until its inputs/evidence exist.

## Non-goals

No embedding, Qdrant/indexing import, retrieval, chat, UI, 100k optimization,
delta export, M8/M9 contract redesign, or fabricated real-run evidence.
