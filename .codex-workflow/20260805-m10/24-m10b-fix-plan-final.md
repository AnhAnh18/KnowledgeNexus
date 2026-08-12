# M10-B Boundary Validation Fix - Final

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Scope

Address only the confirmed M10-B review findings and preserve M6G/M9 schemas,
exporters, CLI, roadmap/state, connectors, network, and real-run behavior. The
existing Windows `Path` compatibility correction remains in this fix.

M10 has eight streams: seven schema-validated non-tombstone streams
(`documents`, `chunks`, `relations`, `acl`, `media_assets`, `symbols`, and
`sync_state`) plus `tombstones`. Initial M10-B handoffs do not accept a
tombstone input; the projected tombstone tuple must be exactly empty.

## Implementation contract

1. Inject a `_SchemaValidator` protocol with callable
   `validate_record(schema_name, record)`. `ComposeM10Snapshot` uses the
   shared `FoundationSchemaValidator` when omitted and rejects non-callable
   validators/adapters at construction. The pure composer receives the
   validator explicitly and validates isolated deep copies with exactly these
   schemas: `CanonicalDocument`, `ChunkRecord`, `RelationRecord`, `ACLRecord`,
   `MediaAsset`, `SymbolRecord`, and `SyncStateRecord`. Validator mutation or
   arbitrary exceptions fail closed with a sanitized projection category; a
   separate untouched defensive copy feeds the projection.

2. Preserve exact handoff field sets and reject wrong runtime values, missing /
   extra fields, forged instances, and malformed records before `.get` or any
   provenance field access. Add exact-field validation to
   `M10CompositionResult` and require callable adapter `collect` methods.

3. Provenance and deterministic ordering:
   - Confluence documents/chunks/media use `source_system=confluence`, selected
     `page_id`, and `source_version == confluence.source_version`; document
     page IDs must be unique and occur in the same relative order as
     `request.ordered_page_ids`, and every chunk/media parent must be an
     emitted selected document.
   - Git documents/chunks use `source_system=git`, relative POSIX `file_path`
     (no backslash, absolute root, or `..` segment), exact `repo`/`branch`, and
     `source_version == request.git_commit`. Git symbols use the same path
     grammar, exact repo/branch/commit/file provenance, and a positive ordered
     line span.
   - Each stream is emitted deterministically by its identity after the
     source/page-order checks. Every document has one ACL record; chunk ACL
     tags exactly equal the parent document ACL tags. A successful Git record
     must carry the exact `repo:<repository>` tag; `restricted:unresolved` is
     deny-safe only as a rejected/failure condition, never as a successful
     M10-B projection.

4. Relations and sync state:
   - All relation records are schema-valid. `resolved` requires an emitted
     target and no unresolved marker. `unresolved_without_jira_api`,
     `deferred_mvp`, and `unresolved_target` require a non-empty target not
     present in emitted entities; for `mentions_jira_key` the target must be
     the explicit `jira:issue:<KEY>` marker. No missing, fabricated,
     `unknown`, or contradictory target is accepted.
   - Sync state is optional but deterministic and unique by entity. Every row
     is schema-valid, `status=active`, has source/entity type consistent with
     Confluence page/attachment or Git file, matches an emitted document/media
     identity, and has `last_seen_version` equal to the corresponding source
     version/commit. Reject duplicates, `error`/`tombstoned`, non-emitted
     entities, and any second row for an entity; an empty sync stream is valid.

5. Media policy and metrics:
   - Non-empty media requires `include_attachments=True` and count `<=
     max_assets`; each asset has the allowed processing status, selected
     Confluence parent/source version, and an existing parent ACL. Raw/content
     provenance is paired: `content_hash` and `raw_uri` are both null for
     non-downloaded assets or both present for downloaded assets, with a
     64-hex content hash and `raw://confluence/attachments/<id>/<hash>` URI
         whose final hash matches; drift or missing provenance fails closed.
   - `parsed|ocr|summarized` count as processed, `failed` as failed, and
     `not_processed` as neither. Populate `media_processed` and
     `media_failed` from emitted statuses.

## Tests and acceptance

Update fixtures to full schema-valid records. Add adversarial coverage for
wrong containers/types, missing/extra/forged fields, validator mutation and
exceptions, provenance/page-order/Git ACL/path/commit drift, ACL inheritance,
all relation statuses and target rules, media budget/status/parent/raw/content
provenance, symbol line drift, sync identity/status/version/cardinality,
duplicates, non-callable adapters, zero calls, atomic failures, exact metrics,
and empty tombstones. Run focused M10-A/M10-B tests, bounded M9/M6G and
architecture regressions, compileall, and diff-check, then obtain a fresh
independent review before roadmap/state updates or commit.
