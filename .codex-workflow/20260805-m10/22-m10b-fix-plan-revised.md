# M10-B Boundary Validation Fix - Revised

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

## Scope

Address only the confirmed findings in
`.codex-workflow/20260805-m10/19-m10b-review-1.md`; preserve M6G/M9 schemas,
exporters, CLI, roadmap/state, connectors, network, and real-run behavior.
The existing Windows `Path` compatibility correction in `m10_snapshot.py`
remains in this bounded M10-B fix.

## Required implementation

1. Add an injected `_SchemaValidator` protocol with callable
   `validate_record(schema_name, record)`. `ComposeM10Snapshot` must accept a
   validator (defaulting to the shared `FoundationSchemaValidator` only when
   omitted), reject a non-callable validator at construction, and pass the
   same validator explicitly to `compose_m10_projection`. The pure function
   must validate, before any field access, these exact schemas:
   `CanonicalDocument`, `ChunkRecord`, `RelationRecord`, `ACLRecord`,
   `MediaAsset`, `SymbolRecord`, and `SyncStateRecord` for their corresponding
   streams. A tombstone stream is forbidden in this initial handoff and the
   projected tuple remains exactly empty.

2. Validate each record on an isolated deep copy, reject validator mutation or
   arbitrary validator exceptions as a sanitized projection failure, and retain
   a separate defensive copy for the projection. Reject wrong record runtime
   types, missing/extra fields, and forged handoff/result instances before
   `.get`/field access. Keep the existing exact handoff field sets and add
   exact-field validation to `M10CompositionResult`; require callable adapter
   `collect` attributes.

3. Enforce source provenance after schema validation:
   - Confluence documents/chunks/media have `source_system=confluence`, a
     selected `page_id` in `request.ordered_page_ids`, and
     `source_version == confluence.source_version`; documents must link to the
     requested scope and chunks must link to an emitted Confluence document.
   - Git documents/chunks have `source_system=git`, non-empty POSIX
     `file_path`, `repo/branch == request.git_repository/git_branch`, and
     `source_version == request.git_commit`; Git symbols must match the exact
     repo/branch/commit/file and use the same approved relative POSIX path
     grammar and positive line span.
   - Every emitted document has one matching ACL record. Chunk ACL tags must
     equal the parent document ACL tags. Git ACL tags are exactly
     `repo:<repository>` or `restricted:unresolved`; Confluence ACL tags must
     be schema-valid and non-empty.

4. Enforce relations and sync state: every relation source and target must be
   schema-valid and its source must be an emitted document/chunk. A
   `mentions_jira_key` unresolved relation must retain its explicit
   `jira:issue:<KEY>` target; no missing/placeholder target is accepted, and
   resolved relations may not use unresolved placeholders. Sync rows are
   optional but, when present, must be unique, `active`, source/entity-type
   consistent (`confluence` page/attachment or Git file), match an emitted
   selected document/media identity, and carry `last_seen_version` equal to
   the corresponding source version/commit. Empty sync state is valid.

5. Enforce media policy: non-empty media requires `include_attachments=True`,
   count `<= max_assets`, allowed processing status, source/version and
   parent-document provenance, and an existing parent ACL (deny-safe inherited
   access). `parsed|ocr|summarized` count as processed; `failed` counts as
   failed; `not_processed` counts neither. Populate `media_processed` and
   `media_failed` from those statuses.

## Tests and acceptance

Update M10-B fixtures to be real schema-valid records and add adversarial
coverage for object/None/wrong containers, missing/forbidden fields, forged
models, schema-invalid records, validator mutation/exception, provenance and
page-order drift, Git ACL/path/commit drift, ACL inheritance, media budget /
status / parent / provenance, unresolved Jira targets, symbol path/line drift,
sync identity/status/version/duplicates, duplicate IDs, non-callable adapters,
zero dependency calls, atomic failures, exact metrics, and empty tombstones.
Run focused M10-A/M10-B tests, bounded M9/M6G compatibility and architecture
regressions, `python -m compileall -q src tests`, and `git diff --check`; then
obtain a fresh independent review before roadmap/state updates or commit.
