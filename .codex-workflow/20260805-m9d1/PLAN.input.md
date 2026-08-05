# M9-D1 Tombstone Contract and Cascade Plan

## Objective

Activate the deferred `TombstoneRecordBuilder` and a pure, atomic tombstone
projection seam for M9-D update propagation. This stage defines schema-valid
tombstone records, deterministic IDs, reason/entity validation, and explicit
cascade expansion. It does not diff snapshots or publish deltas; that is M9-D2.

## Normative inputs

- `contracts/foundation/schemas/tombstone_record.schema.json` and `defs.schema.json`.
- `contracts/foundation/decision_logs/AI_Knowledge_Platform_Master_Spec_v7_1.md` §§16.2, 18.2-18.3.
- `contracts/foundation/CHUNKING_SPEC.md` §7.
- Existing `TombstoneIdGenerator`, `SCHEMA_VERSION`, and Foundation schema
  validator conventions.

## Bounded scope

1. Add exact enums for tombstone entity types (`document`, `chunk`, `relation`,
   `acl`, `media`, `symbol`) and reasons (`source_deleted`, `access_revoked`,
   `moved_out_of_scope`, `content_updated`, `config_invalidated`).
2. Add immutable runtime-validated `TombstoneRequest` and
   `TombstoneProjectionResult` models. Requests require exact non-empty entity
   ID, reason, dataset version, detected timestamp, optional detail/source
   version, and a source-cascade tuple. Results are atomic: success has ordered
   schema-shaped records and exact count; failure has no records and one
   sanitized category.
3. Add `TombstoneRecordBuilder` returning a plain JSON-compatible dictionary
   with exactly the schema fields, deterministic `tombstone_id` from the
   existing generator, optional `detail` and `source_version_last_seen`, and
   schema validation before return.
4. Add a pure `ProjectTombstones` use case that materializes one root entity
   plus explicitly supplied child IDs according to the normative cascade rule:
   document -> chunks, media, relations, ACL, symbols; no invented children.
   Every child receives the same reason/dataset/detected timestamp and its own
   deterministic tombstone ID. Duplicate IDs are rejected unless the exact
   entity/reason tuple is byte-identical, in which case only one record remains.
5. Enforce deterministic ordering by entity-type rank then entity ID; no wall
   clock, filesystem, network, export, checkpoint, raw-store, ACL resolver, or
   Qdrant side effect.

## Explicit non-goals

- No inventory/snapshot diff, changed-content detection, delta manifest, JSONL
  publication, sync database, connector behavior, or full M10 export.
- No automatic inference of access revocation or out-of-scope status.
- No cascade from a child back to its parent; callers provide the root/children.

## Adversarial acceptance

- Schema validation with `additionalProperties: false`, nullable optional
  fields, exact IDs/enums/timestamps, and deterministic byte output.
- Wrong runtime values: `object()`, `None`, wrong enum, missing/extra fields,
  malformed IDs, whitespace IDs, invalid timestamps, forbidden detail sizes,
  impossible count/result combinations, forged frozen objects, duplicate or
  conflicting child tuples.
- Atomicity: malformed later child yields failed result with zero records;
  builder/schema/token exceptions leak no partial output.
- Cascade matrix tests for every reason and document/child entity type; verify
  exact ordering, same reason/timestamp, no duplicate IDs, and no I/O.
- Focused tests, schema/architecture regression, compileall, diff-check, fresh
  independent review, then roadmap/state update and commit/push.

