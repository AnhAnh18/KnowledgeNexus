# M10-B Final Boundary Fix - Approved Revision

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

Address only `.codex-workflow/20260805-m10/27-m10b-review-final.md` findings;
preserve M6G/M9 schemas, exporters, CLI, roadmap/state, connectors, network,
and real-run behavior.

## Required implementation

1. Keep the injected validator seam but pass two explicit validators to the
   pure composer: the injected validator and a canonical shared
   `FoundationSchemaValidator`. The application constructor creates the
   canonical validator when omitted and rejects/sanitizes construction
   failures before any adapter call. For each of the seven non-tombstone
   streams, canonical validation runs first on an untouched deep copy, then
   the injected validator runs on a separate copy; detect mutation in either
   copy and fail closed. A third untouched copy is the only projection input.
   Canonical validation uses `CanonicalDocument`, `ChunkRecord`,
   `RelationRecord`, `ACLRecord`, `MediaAsset`, `SymbolRecord`, and
   `SyncStateRecord`. Initial tombstones have no handoff input and the
   projection tombstone tuple remains exactly empty. All validator/loader
   exceptions are sanitized and atomic.

2. Before merging handoffs, bind ownership:
   - Confluence handoff: document/chunk/ACL/media `source_system=confluence`;
     symbols, Git-only streams, and cross-source relations are forbidden;
     relation sources must be Confluence document/chunk IDs; sync rows must
     use `source_id=request.confluence_scope.source_id`, entity type `page` or
     `attachment`, and IDs from that handoff's documents/media.
   - Git handoff: document/chunk/ACL/symbol `source_system=git`; media and
     relations are forbidden; sync rows use `source_id=request.git_repository`
     and entity type `file` (emitted file) or `repo` (the requested repo ID).
   Reject cross-source records before downstream field access.

3. Apply `_path` to Git documents, chunks, and symbols. Reject unresolved
   relation target placeholders (`unknown`, `none`, `null`, `unresolved`,
   empty, or whitespace). For all unresolved statuses, require explicit
   external identity grammar: Jira mentions use
   `jira:issue:<KEY>`; `includes_page`/`links_to_page` use
   `confluence:page:<id>`; `embeds_media` uses
   `confluence:attachment:<id>`. The external target must not be emitted.
   Resolved targets must be emitted and may not use external/unresolved
   markers.

4. Preserve existing ACL inheritance, media budget/raw-content provenance,
   sync version/cardinality, deterministic ordering, metrics, result exact
   fields, adapter-callability, and sanitized application failure behavior.

## Acceptance

Add adversarial tests for no-op/canonical validator bypass, canonical or
injected validator mutation/exception/constructor failure, missing-field
sanitization, Git chunk traversal/backslash, all unresolved statuses and
placeholder variants, Confluence/Git sync ownership, cross-handoff records,
zero calls, atomic empty output, and all existing M10-B invariants. Run
focused M10-A/M10-B, bounded M9/M6G/architecture, compileall, diff-check, and
fresh independent review before roadmap/state update or commit.
