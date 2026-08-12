# Foundation Completion Plan

Status: implementation closeout, 2026-08-08; external real-input gates pending

Current evidence audit: the operator has completed the real M8-AC mini-corpus
run and supplied its acceptance/chunk handoff. F1-F3 and F6 implementation
gates are test-verified; F4/F5/F7 evaluator and publication tooling are
test-verified. Remaining real-input evidence is OCR/media/M10/second-sync/
scale. Synthetic fixtures and review staging directories do not count as
real-input evidence.

Implementation closeout is now complete through the concrete adapter and
publication boundaries. Remaining work is evidence acquisition and execution:
the code cannot truthfully promote synthetic fixtures to real-input acceptance.

This plan closes Foundation by proving every export stream from trusted source
inputs through the real M10 snapshot. JSON Schemas under
`contracts/foundation/schemas/` remain authoritative. No raw Confluence data,
credentials, runtime artifacts, or unsanitized evidence belongs in Git.

## Definition Of Done

Foundation is complete when one bounded real Confluence + Git run can produce a
published M10 snapshot whose eight JSONL streams and manifest are schema-valid,
cross-linked, ACL-safe, deterministic, and accepted by readback:

- `documents.jsonl`
- `chunks.jsonl`
- `relations.jsonl`
- `acl.jsonl`
- `media_assets.jsonl`
- `symbols.jsonl`
- `sync_state.jsonl`
- `tombstones.jsonl`

The run must also prove a second-sync delta path for changed, deleted, moved-
out-of-scope, and access-revoked entities. Synthetic tests are necessary but do
not close the real-input gates.

## Stream Audit

| Stream/schema | Current state | Closeout gap |
|---|---|---|
| `CanonicalDocument` | Implemented, schema-validated, and wired through concrete Confluence/Git M10 adapters | Real bounded source run and readback |
| `ChunkRecord` | Implemented for Confluence prose/table/code and Git code; ACL/provenance closure enforced | Attachment-derived chunks remain deferred by D20; real bounded run |
| `RelationRecord` | Jira plus generic `embeds_media`, `includes_page`, and `links_to_page`; relation-ID closure enforced | Real bounded media/page evidence |
| `ACLRecord` | Implemented and composed for Confluence/Git with chunk inheritance | Real bounded source run and readback |
| `MediaAsset` | Metadata/body, Draw.io/PDF/OCR seams, parent ownership, and media relations wired | OCR approval and real bounded media gate |
| `SymbolRecord` | M9-C producer wired into Git M10 adapter | Real bounded Git handoff |
| `SyncStateRecord` | Builder/materializer covers pages, attachments, Git files, and repository marker | Real bounded source inventory |
| `TombstoneRecord` | Builder, cascade, delta projector, publisher ownership checks, and strict readback implemented | Real second-sync delta evidence |
| `Manifest` | Full/delta staging, completion, atomic publication, strict readers, and readback implemented | Real full snapshot and scale readback |

## Execution Phases

### F0 - Contract and producer matrix

Create one machine-readable inventory mapping each schema to its producer,
validator, tests, and M10 owner. Add a cross-stream closure checklist:

- every document has one ACL and matching source provenance;
- every chunk points to an emitted document and inherits ACL;
- every relation source exists and every resolved target exists;
- every media asset points to its parent Confluence document;
- every sync row points to an emitted document/media/repository entity;
- every tombstone target belongs to the prior snapshot and cascades correctly.

Exit: no stream is marked complete based only on a dataclass or synthetic
fixture.

### F1 - Generic Confluence relation closure

Keep the Jira path unchanged and add a post-ACL generic relation stage:

1. Wire `embeds_media` materialization into the Confluence handoff.
2. Preserve normalized reference intents through `ProcessConfluencePageSet`;
   the current page-set result only counts them and drops their provenance.
3. Resolve matched attachments; use stable unresolved attachment markers for
   missing or ambiguous references.
4. Materialize `includes_page` from include/excerpt-include intents.
5. Materialize `links_to_page` only for safe, positively identified Confluence
   page targets; preserve external links as page text, not guessed relations.
6. Append relation IDs to the owning document and relevant chunks.
7. Make M10 reject relation IDs that do not exist in `relations`.

Exit: every media/page reference in a bounded corpus produces exactly one
deterministic relation or an explicit unresolved relation with valid grammar.

### F2 - Sync-state producer

Implement a schema-valid `SyncStateRecordBuilder`/materializer from the
authoritative inventory/checkpoint state. It must cover pages, attachments,
Git files, and the Git repository marker, with exact source/version/status
binding. Add adversarial tests for missing entities, duplicate entities,
version drift, impossible status combinations, and forged counters.

Exit: a real handoff never injects sync rows manually.

### F3 - Real source adapters and M10 orchestration

Implement bounded read-only adapters that compose existing approved seams:

- Confluence: preserved raw pages -> normalization/chunks -> Jira/generic
  relations -> ACL -> media assets -> sync state.
- Git: pinned repository source -> documents/chunks/symbols -> ACL -> sync.

Adapters must be side-effect constrained, sanitize failures, preserve source
ordering, and feed `M10ConfluenceHandoff`/`M10GitHandoff` without bypassing the
canonical validator.

Exit: no M10 stream is supplied by a test-only handoff for the real run.

### F4 - Real M8/M9 input gates

Close external-input gates in this order:

1. M8-AC real 10-20 page mini-corpus with approved page selection and exact
   tokenizer assets.
2. M9-A4 OCR engine approval: engine/runtime/model/build identity, offline
   policy, limits, sanitized acceptance evidence, and failure/budget behavior.
3. Bounded media corpus covering Draw.io, digital PDF, image-only PDF, image,
   and chart/screenshot cases.

The M9-A4 approval envelope is validated through the sanitized `ocr` gate of
`evaluate_foundation_gates`; it never accepts raw OCR output or credentials.

MVP remains source-first: tables are authoritative over chart renderings;
Draw.io comes from XML; PDF uses digital text before OCR; no numeric chart
reconstruction; no `attachment_text` chunks until the contract is deliberately
versioned beyond D20.

Media semantic proximity in the MVP is achieved by `parent_document_id` plus
the `embeds_media` relation; the current `MediaAsset` schema has no title or
breadcrumb fields. Indexing should join/enrich from the parent document rather
than adding ad-hoc fields. Standalone media chunks require a separate additive
schema/version phase.

Exit: media assets are processed or explicitly skipped with truthful status and
quality evidence, never silently omitted.

### F5 - First real full snapshot

Run the bounded real M10 export with the agreed Confluence/Git scope. Verify:

- deterministic repeatability;
- all eight JSONL files plus manifest;
- exact counts and quality report;
- relation/media/ACL/sync closure;
- atomic publication and no-clobber rollback;
- sanitized operator output only.

Exit: real M10 full-snapshot gate passes.

### F6 - Second-sync lifecycle closure

Use the first snapshot as prior state and prove changed, deleted,
access-revoked, and moved-out-of-scope cases. Tombstones must cascade to
chunks, media, relations, and ACL according to the contract. ACL-only changes
must re-emit affected ACL/chunks without inventing content tombstones.

Exit: delta export is real-input accepted, not only read-only projected.

### F7 - Scale and hardening (after functional closeout)

Only after F5/F6 pass, address the deferred M7 scale gate: production transport,
RSS/resource measurement, 10k/100k evidence, and performance tuning. Keep PLM
M11 on hold until sanitized read-only PLM evidence is available.

## Priority Order

1. F0 matrix and cross-stream closure tests.
2. F1 generic relations and media wiring.
3. F2 sync-state producer.
4. F3 real Confluence/Git adapters.
5. F4 M8/M9 real-input gates.
6. F5 real full snapshot.
7. F6 second-sync tombstone/delta acceptance.
8. F7 scale hardening; PLM remains deferred.

## Non-Goals For This Closeout

- Embeddings, Qdrant, retrieval, reranking, chat, or Gauss.
- Full visual reasoning or exact numeric reconstruction from chart pixels.
- Attachment-derived chunks before an additive schema/contract decision.
- PLM ingestion before real sanitized API evidence.
