RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10 Plan Review

M10 is a legitimate next milestone, but the input is not yet an actionable
implementation plan. It spans a new multi-source trust boundary, graph
projection, and publication orchestration, and it conflicts with existing
active M6G/ M3 assumptions unless those differences are explicitly resolved.

## Contract and gate blockers

1. Define the normative M10 contract (or an approved extension to
   `ONE_PAGE_EXPORT_SPEC.md`) before production implementation. The active
   contract is one trusted Confluence page with fixed `dataset_name`,
   `source_id`, `export_mode`, `schemas_version`, source-scope shape, profile
   and config-hash derivation, and empty media/symbol/sync/tombstone streams.
   M10 instead proposes an approved Confluence scope plus Git, populated media
   and symbols, and cross-stream sync/tombstone checks. State exactly which
   rules remain locked, which are generalized, and how compatibility with the
   M6G golden export is preserved. Do not silently widen the one-page public
   contract.

2. The roadmap says M8-AC's real gate is still `pending_external_input` and
   M10 requires real operator inputs. Separate synthetic implementation,
   source-review approval, and the operator-approved real run. M10 may be
   developed offline, but it must not claim a real full-snapshot PASS or update
   roadmap state without approved generation/scope, pinned tokenizer assets,
   credentials handled outside evidence, and sanitized aggregate acceptance.

3. Resolve the stream/deferred contradiction. The current
   `FullSnapshotStagingCompleter` extended path enforces empty
   `media_assets`, `symbols`, `sync_state`, and `tombstones`, while M10-B/C
   proposes composing media and symbols and validating those streams. Specify
   whether M10 keeps all four empty, or add a backward-compatible, independently
   contracted quality/completion mode that permits populated media/symbols
   without changing M6G behavior or creating a parallel completer/exporter.

4. Clarify artifact counting: a published version directory contains exactly
   ten files (eight JSONL streams, `manifest.json`, and `quality_report.md`);
   `LATEST.txt` is a separate dataset-root pointer and must not be counted as a
   version artifact. Manifest `counts` must contain exactly the eight stream
   keys and equal records actually emitted.

## Required design detail

- Specify exact immutable runtime-validated fields, field sets, enums, limits,
  and status/result invariants for M10-A. Include run/generation identity,
  scope and exclusion grammar, source provenance, Git repository/branch/commit,
  media policy, profile/config identity, `generated_at` preservation and
  dataset-root rules. Require exact-type checks, missing/extra-field rejection,
  forged frozen-object revalidation, no secret/raw-content fields, and
  impossible-counter rejection before any dependency or filesystem call.
- Reuse the approved M6G profile bundle derivation: hash the exact normalized
  bytes of the loaded embedding and Jira profiles with the code-owned
  normalization-policy identity. Do not accept an arbitrary operator
  `config_hash`, independently loaded text/object pairs, or a second
  chunker/profile identity. Preserve the caller's valid RFC3339
  `generated_at` representation while using the existing deterministic
  `DatasetVersionGenerator`; define `dataset_version`/folder/`LATEST.txt`
  equality.
- Define trusted adapter ports and handoff models for M7 raw generations,
  M8-D/E page sets, ACL materialization, Jira relations, M9-A media, M9-B Git,
  and M9-C symbols. Each handoff must bind generation, source, document, commit,
  path, and profile identity; validate exact provenance before field access;
  use deterministic source ordering; and return sanitized category-only
  failures. State which adapters may read/write raw evidence and where all
  outputs remain in-memory until M3 staging.
- Pin Git by repository, branch, and immutable commit. Define path containment,
  POSIX/casefold policy, generated/vendor/binary exclusions, and how Git chunks
  receive deny-safe ACL tags. A branch name alone must never select mutable
  source bytes.
- Define Confluence scope/exclusion semantics, page ordering, source-version
  and raw-generation checks, restriction/attachment observation provenance,
  and all-or-nothing behavior across mixed Confluence/Git/media/symbol
  failures. Do not refetch or reinterpret M8/M9-owned policy in the M10
  orchestrator.
- Make every cross-stream rule executable: document/chunk identity and source
  ownership, non-empty deny-safe ACL tags, ACL/document cardinality, relation
  source/target resolution and unresolved-reference policy, media parent and
  ACL inheritance, symbol-to-chunk linkage, and sync/tombstone entity/version
  consistency. State whether invalid references fail the whole run or are
  dropped/quarantined; no silent loss or fabricated deletion evidence.
- Reuse `FullSnapshotStagingWriter`, `FullSnapshotStagingCompleter`,
  `FullSnapshotPublisher`, and `DatasetVersionGenerator`. If their current
  one-page-only assumptions require extension, specify an additive API and
  preserve old arguments, report bytes, file-set checks, cleanup, no-clobber,
  and golden output. Do not import private M6G CLI state or create a parallel
  writer/completer/publisher.
- Preserve the existing CLI's arguments, exit mappings 1-13, reserved M6G
  categories 14-19, structured configuration-failure stderr vocabulary, and
  sanitized output. Define M10 error-stage/category mapping for adapter,
  projection, staging, completion, publication, and post-publication
  acceptance failures; never print exception text, paths, IDs, URLs,
  principals, content, or hashes.

## Required tests and acceptance criteria

- Model and boundary adversarial tests for `object()`, `None`, wrong runtime
  containers/types/enums, missing and forbidden extra fields, forged frozen
  inputs/results, invalid provenance/paths/timestamps, secret/raw-content
  attempts, and impossible cross-field counters. Assert fail-closed categories,
  no dependency calls, and zero partial records/files.
- Synthetic end-to-end fixtures must include both non-empty Confluence and Git
  streams, media and symbols where the selected policy permits them, and the
  explicit empty initial tombstone/sync behavior. Verify all eight JSONL files,
  manifest schema/counts, deterministic ordering, canonical IDs, ACL/relation/
  media/symbol graph invariants, source/profile/config provenance, and exact
  ten-file publication layout.
- Negative orchestration tests must cover malformed adapter results, identity
  drift, unresolved relations/symbols, ACL gaps, duplicate/collision IDs,
  schema-validator rejection or mutation, count mismatch, pre-existing
  staging/final paths, symlinks/reparse points, unsafe roots, publication and
  completion failures, `LATEST.txt` corruption, and failed-run atomicity with
  the prior pointer unchanged.
- Determinism tests must run the same immutable inputs twice (including source
  ordering permutations and equivalent timestamp offsets where permitted),
  compare canonical stream bytes/manifest/report, and define no-clobber
  behavior for an already published version.
- Run focused M10 tests, all affected M7/M8/M9/M3/M6G regressions, architecture
  checks, `python -m compileall -q src tests`, and scoped `git diff --check`.
  Perform a fresh independent review in a new session; only after `PASS` may
  roadmap/state be updated and changes committed/pushed. Real-run evidence
  must be aggregate-only and remain outside Git.

## Scope decision

The plan must be revised into separately reviewable seams (at minimum:
trusted composition/projection, generic-compatible export completion, CLI
publication boundary, and synthetic acceptance) with explicit approval gates.
No embedding, Qdrant, indexing, retrieval, chat, delta export, or redesign of
M8/M9 contracts is authorized by this review.
