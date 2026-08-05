# M10-C Cross-Stream Projection and Generic Completion - Final Approved

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

M10-B is complete and independently reviewed `PASS`; M8-AC remains
`pending_external_input`. Add only generic M10 completion behavior and keep
the legacy M6G path byte-identical.

## Boundary and authoritative validation

The additive signature is
`complete(*, staging_path, validator, one_page_quality=None, m10_quality=None)`.
When `m10_quality is None`, execute the existing legacy path unchanged. In
generic mode, require exact `M10QualityReportInput`, `one_page_quality is None`,
and the exact concrete shared `FoundationSchemaValidator` (reject protocol
fakes/subclasses) before filesystem inspection or report mutation. Constructing
the canonical validator, strict parsing, schema validation, or report checks
must sanitize failures and leave no report/stream side effects.

Strictly read manifest/JSONL (duplicate keys and non-finite constants rejected),
then validate untouched deep copies with the canonical validator before counts
or field access; detect validator mutation/exception. Use separate defensive
copies for all later checks/rendering and detect quality-input/renderer
mutation.

## Generic invariants and report contract

- Manifest counts contain exactly the eight stream keys, non-negative integers,
  and equal both on-disk counts and `m10_quality.expected_counts`.
- Manifest `source_scopes` contains exactly sorted `confluence` and optional
  `git`; Confluence fields are exactly `source_id`, `space_keys`,
  `root_page_ids`, `page_ids`; Git fields are exactly `repository`, `branch`,
  `commit`. Values are non-empty one-line identifiers, ordered unique arrays,
  and lowercase 40-hex commit. Canonical JSON must equal the typed quality
  input source scopes.
- `media_assets`, `symbols`, and `sync_state` may be non-empty;
  `tombstones.jsonl` must be empty for initial M10 full snapshot.
- Generic quality metric sections have exact integer-key sets:
  `jira_metrics = (relations_total, resolved, unresolved,
  unresolved_without_jira_api, deferred_mvp, unresolved_target)`,
  `acl_metrics = (documents_total, documents_with_acl, restricted_documents,
  default_deny_chunks)`,
  `media_metrics = (assets_total, processed, failed, not_processed)`,
  `symbol_metrics = (symbols_total, resolved)`,
  `sync_metrics = (rows_total, active, pages, attachments, files, repos)`, and
  `tombstone_metrics = (rows_total, initial_empty)`. Values are actual
  non-negative integers and cross-counts are consistent. Completion checks have
  exactly `(schema_validation, counts_match, tombstones_empty,
  projection_consistency)` with boolean values.
- Profile strings are non-empty one-line safe identifiers; report rendering
  accepts no arbitrary strings in metric/check mappings and therefore cannot
  emit paths, URLs, principals, hashes, exception text, secrets, record text,
  or raw content.

Render exactly twelve UTF-8 sections in this order: `Snapshot`, `Active
Profiles`, `Record Counts`, `Jira Relation Quality`, `ACL Quality`, `Media
Quality`, `Symbol Quality`, `Sync State`, `Tombstones`, `Completion Checks`,
`Publication State`, `Scope`. Keys are fixed as above; publication includes
`PENDING_AT_REPORT_COMPLETION` markers. Rendering is pure and deterministic.

Reuse existing no-clobber/cleanup behavior: validate before writing, remove
only an owned report on write/final-set failure, preserve machine streams, and
do not derive versions or write `LATEST.txt`.

## Acceptance

Add adversarial generic-mode tests for wrong/forged quality inputs, both modes,
fake/subclass validators, strict duplicate/NaN input, schema-invalid records,
validator/quality mutation or exception, count/source-scope drift, non-empty
media/symbol/sync, non-empty tombstones, unsafe/pre-existing report paths,
cleanup/no-clobber, deterministic repeated bytes, sanitization, and all M6G
golden/one-page tests. Run focused M10-C, existing M6G exporter, architecture,
compileall, diff-check, then fresh independent review before roadmap/state and
commit/push. No CLI/publisher/network/raw/checkpoint/real-run changes.
