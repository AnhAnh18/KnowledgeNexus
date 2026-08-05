# M10 First Full POC Foundation Snapshot - Implementation Plan

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## 1. Scope and compatibility lock

Add a multi-source M10 seam without widening the approved M6G one-page public
models or changing their CLI, quality-report bytes, deferred-stream policy, or
golden fixture. Reuse M3 writer/publisher APIs; add only an additive generic
completion/report mode. M8-AC real evidence remains external and
`pending_external_input`; the initial snapshot has empty tombstones, while
M9-D is required before a second sync or first delta export.

The published version directory has exactly ten files: the eight JSONL streams,
`manifest.json`, and `quality_report.md`. `LATEST.txt` is a separate pointer at
the dataset root. Manifest `counts` has exactly the eight stream keys.

## 2. Exact M10 wire models and constants

Add frozen exact-field models with `type(...)` checks, no missing/extra fields,
defensive copies, and forged-instance revalidation:

### `M10ConfluenceScope`

Fields: `source_id: str`, `space_keys: tuple[str, ...]`,
`root_page_ids: tuple[str, ...]`, `page_ids: tuple[str, ...]`.
All strings are NFC one-line non-empty identifiers; tuples are non-empty,
sorted where set-like, unique; every page ID is in the approved roots/scope.

### `M10ConfluenceExclusion`

Fields: `page_id: str`, `reason: str`; exact reason enum is
`exclude_subtree|exclude_page`; page ID is canonical and exclusion tuples are
ordinally deterministic with no duplicates.

### `M10MediaPolicy`

Fields: `include_attachments: bool`, `allow_download: bool`,
`allowed_processing_statuses: tuple[str, ...]`, `max_assets: int`.
Allowed processing values are the schema enum
`parsed|ocr|summarized|not_processed|failed`; the tuple is sorted/unique,
`max_assets` is non-negative, and `allow_download` cannot be true when
`include_attachments` is false.

### `M10SnapshotRequest`

Fields: `run_id: CrawlRunId`, `generation_id: CrawlRunId`,
`confluence_scope: M10ConfluenceScope`,
`confluence_exclusions: tuple[M10ConfluenceExclusion, ...]`,
`ordered_page_ids: tuple[str, ...]`, `raw_generation_id: str`,
`git_repository: str`, `git_branch: str`, `git_commit: str`,
`media_policy: M10MediaPolicy`, `profile_bundle: OnePageExportProfileBundle`,
`generated_at: str`, `dataset_root: Path`, `export_mode: str`.
`run_id == generation_id`; ordered pages are unique/scope-valid;
`raw_generation_id` is non-empty; repo/branch use the approved POSIX grammar;
commit is exactly 40 lowercase hex; `generated_at` is strict RFC3339;
dataset root is absolute, a plain directory, and not a symlink/reparse point;
`export_mode == "full_snapshot"`.

### `M10SnapshotMetrics`

Exact integer fields:
`documents`, `chunks`, `relations`, `acl`, `media_assets`, `symbols`,
`sync_state`, `tombstones`, `confluence_documents`, `git_documents`,
`unresolved_relations`, `media_processed`, `media_failed`,
`symbols_resolved`, `default_deny_chunks`.
All are non-negative; first eight equal stream lengths;
`confluence_documents + git_documents == documents`;
`unresolved_relations <= relations`; `media_processed + media_failed <= media_assets`;
`symbols_resolved <= symbols`; `default_deny_chunks <= chunks`.

### `M10SnapshotProjection`

Fields: `dataset_name: str`, `schemas_version: str`,
`source_scopes: dict[str, object]`, `generated_at: str`, `config_hash: str`,
`chunker_version: str`, `export_mode: str`, the eight ordered tuple streams,
and `metrics: M10SnapshotMetrics`.
Code-owned constants are `dataset_name="spen_knowledge_poc"`,
`schemas_version="1.0"`, and `export_mode="full_snapshot"`; `source_scopes`
has only sorted `confluence` and optional `git` entries with approved fields.

### `M10SnapshotResult`

Fields: `status: Literal["composed", "staged", "published", "failed"]`,
`metrics: M10SnapshotMetrics | None`, `digest: str | None`,
`dataset_version: str | None`, `final_path: Path | None`,
`failure_category: Literal["invalid_request", "adapter", "projection",
"staging", "completion", "publication", "acceptance"] | None`.
`composed` requires metrics/digest and forbids final path/failure;
`staged` additionally requires dataset version and forbids final path/failure;
`published` additionally requires final path and forbids failure;
`failed` requires failure category and forbids metrics/digest/version/path.
Digest is lowercase SHA-256 of canonical projection bytes.

### `M10QualityReportInput`

Exact fields: `active_profile`, `profile_status`, `chunker_version`,
`expected_counts: dict[str, int]`, `source_scopes`,
`jira_metrics`, `acl_metrics`, `media_metrics`, `symbol_metrics`,
`sync_metrics`, `tombstone_metrics`, `completion_checks`.
Report sections and field order are fixed: `Snapshot`, `Active Profiles`,
`Record Counts`, `Jira Relation Quality`, `ACL Quality`, `Media Quality`,
`Symbol Quality`, `Sync State`, `Tombstones`, `Completion Checks`,
`Publication State`, `Scope`. Before publication it must say exactly
`PENDING_AT_REPORT_COMPLETION`; it never contains record text/secrets.

Config derivation reuses M6G's normalized embedding/Jira profile bytes,
`ONE_PAGE_NORMALIZATION_POLICY_ID`, `OnePageExportProfileBundle`, lowercase
SHA-256, and the loaded `ChunkingProfile.chunker_version`. No arbitrary hash,
independent profile text, or caller-supplied chunker version is accepted.
`generated_at` is copied byte-for-byte into the manifest; only
`DatasetVersionGenerator` derives dataset version/folder/LATEST.

## 3. Trusted adapter contracts

Define injected protocols and exact handoff validation:

- Confluence adapter returns a typed generation-bound result containing
  `run_id`, `generation_id`, `source_version`, ordered page results, raw
  artifact identity, ACL/relation/media results, and sanitized category errors.
  Any page/dependency failure aborts the whole projection before staging.
- Git adapter returns a typed commit-bound result containing repository, branch,
  commit, ordered documents/symbols, POSIX paths and line spans. Every Git
  chunk has `acl_tags=["repo:<repository>"]`; if policy cannot establish that,
  it emits `restricted:unresolved` and the run fails the deny-safe gate.
- Media handoffs carry parent document ID and content/raw provenance; allowed
  processing statuses follow `M10MediaPolicy`. Symbols carry exact
  repo/branch/commit/file/line identity and resolve to an emitted chunk when
  `chunk_id` is non-null.
- Relations use schema `resolution_status` values
  `resolved|unresolved_without_jira_api|deferred_mvp|unresolved_target`; an
  unresolved external Jira target remains explicit and is counted, never
  fabricated or silently dropped.
- Sync state is diagnostic only. It may be empty or contain exactly one
  schema-valid `active` record per selected page/file/repo/attachment entity;
  source/entity/version fields must match emitted records, schema version must
  match, and `error`/`tombstoned` statuses are forbidden for initial success.
- Initial `tombstones` is exactly empty. Media and symbols may be empty only
  when their policy/eligible source set is empty; populated records must pass
  all parent/provenance/ACL/linkage checks.

All adapters reject wrong runtime types before field access and return atomic,
sanitized results. No output is written until projection validation completes.

## 4. Projection, generic completion, and publication

- Validate every stream against its JSON Schema and enforce document/chunk
  identity, non-empty deny-safe ACL tags, source ownership, relation policy,
  media parent/ACL inheritance, symbol linkage, sync consistency, deterministic
  ordering, exact counts, and collision-free IDs.
- Additive generic completer API must preserve the existing one-page API,
  output bytes, deferred checks, cleanup, and golden fixture byte-for-byte.
- Reuse `FullSnapshotStagingWriter`, `FullSnapshotStagingCompleter`,
  `FullSnapshotPublisher`, and `DatasetVersionGenerator` only.
- CLI mapping is closed: `invalid_request -> 2`, `adapter/projection -> 15`,
  `staging -> 16`, `completion -> 17`, `publication -> 18`,
  `acceptance -> 19`; existing M6G codes 1-19 and structured configuration
  stderr remain unchanged.
- Enforce dataset-root containment, plain-directory/no symlink/reparse,
  staging/final no-clobber, prior LATEST preservation on failure, exact ten-file
  version layout, and sanitized stdout/stderr with no paths/IDs/URLs/principals/
  content/hashes/exception text.
- After publication, read back all ten files and verify schemas, counts,
  manifest/version-directory/LATEST equality, unchanged report bytes, and
  pointer preservation after any failed run.

## 5. Implementation gates and exact validation

Implement in independently reviewable gates: (a) models/adapters, (b) pure
cross-stream projection, (c) generic completion/M3 publication, (d) CLI, (e)
synthetic acceptance. Each gate gets focused adversarial tests and no roadmap/
state update occurs before final independent PASS.

```text
python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/application/use_cases/test_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-models
python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py tests/foundation/infrastructure/exporters/test_one_page_full_snapshot_exporter.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-export
python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/pytest-m10-arch
python -m pytest -q tests/foundation/domain/models/test_confluence_page_set.py tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/domain/models/test_chunk_stability.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-m8
python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-m9
python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/pytest-m10-m3-m6g
python -m compileall -q src tests
git diff --check
```

Obtain a fresh independent review in a new session; fix every P0-P3 finding,
rerun these commands, then update roadmap/state, commit, and push. Real
operator full-POC evidence remains aggregate-only and `pending_external_input`
until supplied; no synthetic result may be promoted to real PASS.

## Non-goals

No embedding, Qdrant/indexing import, retrieval, chat, UI, 100k optimization,
delta export, M8/M9 contract redesign, or fabricated real-run evidence.
