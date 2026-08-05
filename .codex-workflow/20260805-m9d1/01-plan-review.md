RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# Plan Critique

The objective and non-goals are useful, but the implementation contract is not yet actionable enough for a safe build. The main risks are undefined public APIs, ambiguous cascade input, and invariants that cannot be tested from the current wording.

## Concrete gaps and risks

1. **Public API is unspecified (P1).** The plan names `TombstoneRequest`, `TombstoneProjectionResult`, `TombstoneRecordBuilder`, and `ProjectTombstones` but does not specify module paths, constructor/execute signatures, status and failure enums, or whether invalid input raises or returns a failed result. Define the exact importable API and error/status vocabulary before implementation.

2. **Cascade input shape is ambiguous (P1).** "Source-cascade tuple" and "explicitly supplied child IDs" do not say whether a child is `(entity_type, entity_id)`, a typed collection per entity type, or an untyped ID. Untyped IDs cannot validate the different chunk/relation/ACL grammars. Specify the canonical representation, whether empty child collections are allowed, and that only a document root expands; non-document roots must not accept or expand children.

3. **Entity-ID validation is underdefined (P1).** The schema only applies `opaqueId` to `entity_id`, while the acceptance criteria require malformed IDs to fail. State whether validation is schema-only (non-empty/no whitespace) or adds per-entity grammars (`chunk:`, `rel:`, `acl:`, etc.), and document valid document/media/symbol ID forms so the builder does not invent stricter rules than the contract.

4. **Optional-field semantics are missing (P1).** `detail` and `source_version_last_seen` are nullable but optional. Specify whether omitted values are omitted from the dictionary or emitted as `null`, and whether root detail/source-version metadata propagates to children. Also define any detail length/content limit; the current schema has no `maxLength` despite "forbidden detail sizes" in acceptance.

5. **Deterministic bytes are not defined (P1).** A plain dictionary has no byte representation. Specify the canonical serialization used by tests (key order, separators, Unicode handling, and whether `sort_keys` is required), and whether deterministic output means equal dictionaries or equal serialized JSON. Clarify whether timestamps are preserved verbatim or canonicalized.

6. **Timestamp and version rules need precision (P1).** `format: date-time` is only enforced when the validator uses a format checker. Define the validator convention, accepted UTC/offset forms, and rejection of naive/non-string values. Define dataset/source-version grammar and whitespace handling; only dataset `minLength: 1` is currently supplied by the schema.

7. **Duplicate policy is internally unclear (P1).** The plan says duplicate IDs are rejected unless the "exact entity/reason tuple is byte-identical," but a tuple of entity/reason is not a byte-identical record and the generator excludes detail, timestamp, and source version from the ID. Define the deduplication key and behavior for same key with differing metadata, duplicate generated IDs from a hash collision, and duplicate root/child entries. Require deterministic first/last handling or unconditional failure.

8. **Ordering rank is not normative (P1).** "Entity-type rank" has no listed order, and ID ordering is not defined for non-ASCII values. Publish the exact rank (for example, document/chunk/media/relation/acl/symbol) and byte/code-point ordering. Add a test proving output is independent of input tuple order.

9. **Atomic result contract is incomplete (P1).** "Failure has no records and one sanitized category" and "exact count" lack field names and invariants. Specify status, records, count, and error-category types; require `count == len(records)` on success, `count == 0` on failure, and forbid error fields on success/records on failure. Define the allowed sanitized categories and the exception boundary (catch `Exception`, not process-control exceptions).

10. **Immutability is not enforceable as written (P1).** Frozen dataclasses do not freeze nested tuples of mutable dictionaries, and "forged frozen objects" needs a boundary rule. Require exact runtime type checks and revalidation at the use-case boundary, defensive copies or immutable record storage, and mutation tests for request child collections, result records, and objects built via `object.__new__`/`object.__setattr__`.

11. **Schema-validator integration is underspecified (P2).** Identify the existing validator helper, reference resolution setup, and whether validation occurs before and after any normalization. Add tests for validator exceptions and mutated/partial dictionaries to prove no partial output escapes.

12. **Integration/export boundaries are not named (P2).** "Activate the deferred builder" does not say which package `__init__` exports change or whether `ProjectTombstones` is intentionally not wired into the existing full-snapshot exporters. State the exact files/modules allowed to change and add a regression test that current full-snapshot output remains tombstone-empty unless explicitly invoked by this seam.

13. **Purity acceptance needs executable checks (P2).** "No I/O" should include no clock or environment access and no implicit network/filesystem calls. Add monkeypatch guards for `open`, `Path`, `datetime.now/utcnow`, network clients, export writers, checkpoints, raw stores, ACL resolvers, and Qdrant; assert the use case still works with all guards failing.

14. **Cascade semantics need reason coverage detail (P2).** The normative rule says a document tombstone cascades to chunks, media, relations, ACL, and symbols, but the plan does not state whether every reason cascades identically (especially `content_updated`, `config_invalidated`, and `access_revoked`) or how an explicitly supplied child with a conflicting reason is handled. Define this and test all five reasons, all six entity types, empty and maximal child sets, and child IDs repeated across categories.

## Required acceptance/test additions

- Constructor and use-case boundary tests for `object()`, `None`, subclasses/wrong container types, missing fields, forbidden fields, booleans where integers are expected, invalid enums, whitespace IDs, malformed timestamps, and malformed child tuples; assert failure occurs before field access or side effects.
- Golden schema tests for every optional-field combination, exact key set, `SCHEMA_VERSION`, per-entity ID policy, validator format checking, and canonical serialized bytes.
- Property/table tests covering every reason, root entity type, cascade category, duplicate/conflict case, permutation of input order, and deterministic IDs.
- Atomicity tests where a later child fails, the builder raises, or schema validation raises; assert no records/count leak and only one sanitized error category is returned.
- Mutation/forgery tests for frozen requests/results and nested records, plus architecture tests proving the seam remains pure and existing exporters are unchanged.

Until these contracts are made explicit, two conforming implementations could differ on child representation, null/omitted fields, duplicate handling, ordering, and failure behavior.
