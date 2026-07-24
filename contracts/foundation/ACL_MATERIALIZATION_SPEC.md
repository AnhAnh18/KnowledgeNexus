# ACL Materialization Contract

Status: active for Foundation M6F. This focused spec narrows and clarifies
Master Spec v7.1 §14 only for the explicit decisions listed here. It does not
change any JSON Schema and does not rewrite unrelated historical decision logs.

Precedence: `schemas/` win every field-level dispute. This spec sits with the
other active task-focused specs (`CHUNKING_SPEC.md`, `JIRA_RELATION_SPEC.md`)
above v7.1.

## 1. Scope and staging

M6F materializes one page's deny-safe ACL from trusted, already-approved inputs:

- the M6E `ConfluenceJiraRelationResult` (enriched CanonicalDocument, enriched
  ChunkRecords, RelationRecords, quality observation, and metrics), and
- the M6B normalized view-restriction observation chain for the same page.

M6F is split so that each task carries one primary concept:

- **M6F-A (this task):** the normative contract plus strict, pure
  validation/provenance boundaries and principal projection helpers required by
  later stages. M6F-A does **not** compute an effective ACL, does not build an
  `ACLRecord`, does not change `ChunkRecord.acl_tags`, and performs no
  filesystem or network access.
- **M6F-B:** deny-safe effective ACL computation, `ACLRecord` construction, and
  `ChunkRecord.acl_tags` propagation, following the policy locked in §4–§9.
- **M6F-C1:** an opt-in capture mode on the existing M6B operator command
  (§10).
- **M6F-C2:** an offline acceptance CLI binding a captured/synthetic sidecar to
  preserved M6A raw bytes (§11).

M6F never re-parses raw HTTP bodies and never re-derives `created_at`.
`classification` emitted by M6B is the normalized authority; M6F must not
override it from `http_status`.

ACL materialization itself never calls Confluence: M6F-A, M6F-B, and M6F-C2
never perform any network request. The single exception is M6F-C1, which may
invoke the approved M6B read-only collection path only during a separately
authorized controlled live capture (§10); the offline ACL stages then consume
the captured observations.

## 2. Trusted M6E result boundary (validated by M6F-A)

M6F consumes the real domain result `ConfluenceJiraRelationResult` and its real
fields `enriched_canonical_document`, `enriched_chunks`, `relations`,
`quality_observation`, and `metrics`. The quality model is
`JiraRelationQualityObservation(unique_key_like_candidates, allowlisted_keys,
outside_allowlist_keys)`. No parallel DTO is introduced and no nonexistent
result or quality field is referenced.

### 2.1 CanonicalDocument provenance

The enriched CanonicalDocument passes the shared Foundation `CanonicalDocument`
schema validator and additionally satisfies, without mutation:

- `source_system == "confluence"` and `source_type == "wiki_page"`.
- `page_id` is a valid Confluence page ID.
- `document_id == DocumentIdGenerator.confluence_page_id(page_id)`.
- `acl_id == AclIdGenerator.generate_acl_id(document_id)`.
- `source_version` is a non-empty string.
- `jira_keys` is present and is an array with no duplicate.
- `relation_ids` is present and is an array with no duplicate.
- ordered Jira/relation closure holds (§2.3).

`space_key` is **not** required to be non-null or representable at this stage;
the CanonicalDocument schema permits values that cannot later form a space ACL
tag. Space representability is a §5.4 concern, not a provenance failure.

### 2.2 Chunk provenance

Every enriched chunk passes the shared `ChunkRecord` schema validator and
additionally, without mutation:

- equals the enriched CanonicalDocument on exactly these eight fields:
  `document_id`, `source_system`, `source_type`, `title`, `space_key`,
  `page_id`, `source_version`, `updated_at`;
- `jira_keys` and `relation_ids` are present and exactly equal the canonical
  `jira_keys` and `relation_ids`;
- `chunk_id` values are unique in the ordered tuple;
- `text` is a string and `content_hash == ContentHasher.hash_text(text)`;
- `acl_tags == ["restricted:unresolved"]` (still pristine default-deny; the ACL
  stage has not run);
- chunk order is preserved.

Zero chunks is valid. "Belongs to the same document" is not a sufficient check.

### 2.3 Relation provenance

For each Jira key in canonical source order, with
`jira_key = canonical_document["jira_keys"][index]`:

```
expected_target_id   = DocumentIdGenerator.source_entity_id("jira", "issue", jira_key)
expected_relation_id = RelationIdGenerator.generate_relation_id(
                           canonical_document["document_id"],
                           "mentions_jira_key",
                           expected_target_id)
```

The corresponding RelationRecord is schema-valid and exactly satisfies:
`schema_version == "1.0"`, `source_id == canonical_document["document_id"]`,
`target_id == expected_target_id`, `relation_id == expected_relation_id`,
`relation_type == "mentions_jira_key"`, `evidence == "regex:page_body"`,
`confidence == 0.95`, `resolution_status == "unresolved_without_jira_api"`.
`created_at` must be schema-valid and remain unchanged; M6F does not derive it
again.

Ordered closure is exact:
`len(jira_keys) == len(relation_ids) == len(relations)` and, for every index,
`relation_ids[index] == relations[index]["relation_id"]`.

Schema validity alone is insufficient. A schema-valid record with the wrong
source, target, relation ID, type, evidence, confidence, resolution status, or a
wrong relation order is rejected. Production code calls the existing generators
and never duplicates their hash or ID formulas.

### 2.4 Quality provenance

Read `unique_key_like_candidates`, `allowlisted_keys`, and
`outside_allowlist_keys`. Each collection contains only non-empty strings with
no duplicate and retains source-first order. `tuple(allowlisted_keys) ==
tuple(canonical_document["jira_keys"])`. Allowlisted and outside candidates are
disjoint, together fully partition `unique_key_like_candidates`, and are each
ordered subsequences of it. Equivalent set membership in a different order
fails. These collections are never sorted and never leak through exceptions,
logs, or repr.

### 2.5 Metric provenance

`metrics` contains exactly these eight keys and no other: `candidate_occurrences`,
`unique_key_like_count`, `allowlisted_unique_count`,
`outside_allowlist_unique_count`, `duplicate_occurrences`, `relations_total`,
`documents_enriched`, `chunks_enriched`. Every value is a non-negative integer;
`bool` is rejected even though it subclasses `int`.

Six values are independently derived and required:

```
unique_key_like_count          == len(quality.unique_key_like_candidates)
allowlisted_unique_count       == len(quality.allowlisted_keys)
outside_allowlist_unique_count == len(quality.outside_allowlist_keys)
relations_total                == len(result.relations)
documents_enriched             == (1 if result.relations else 0)
chunks_enriched                == (len(result.enriched_chunks) if result.relations else 0)
```

The complete duplicate-occurrence sequence is **not** retained in the
ownership-isolated M6E result (its nested JSON values remain mutable; the result
is not deeply immutable). `candidate_occurrences` and `duplicate_occurrences`
are therefore validated by type, range, and algebra only:

```
candidate_occurrences >= unique_key_like_count
duplicate_occurrences == candidate_occurrences - unique_key_like_count
```

M6F does not claim independent reconstruction of `candidate_occurrences` or
`duplicate_occurrences` and does not reopen M6E to retain occurrence history. A
large but algebraically consistent `candidate_occurrences` is valid at this
boundary.

## 3. Trusted M6B restriction observation boundary (validated by M6F-A)

M6F validates the exact normalized shape already emitted by M6B, which is the
five-field observation dictionary:

```
{ "source_page_id": str,
  "http_status": int,
  "classification": "unavailable" | "unrestricted" | "restricted",
  "users": list[dict[str, str]],
  "groups": list[dict[str, str]] }
```

Each observation contains exactly these five fields; there are no fields named
`availability`, `restriction_state`, `target_role`, or `ancestor_index`. Tuple
order is authoritative: root ancestor → descendants → direct parent → selected
page last.

Domain validation requires: a non-empty observation tuple; valid, unique
Confluence `source_page_id` values; the selected page occurs exactly once and is
the final observation; and the selected `source_page_id` equals the canonical
`page_id`. Exact ancestry equality with the M6A raw page belongs to M6F-C2, not
M6F-A.

### 3.1 Cross-field rules

`http_status` never accepts `bool`. Then:

- `classification == "unavailable"`: `http_status in {200, 401, 403, 404}`,
  `users == []`, `groups == []`. A 200 classified `unavailable` is valid because
  M6B uses `unavailable` when a response cannot be converted into a trusted
  restriction payload.
- `classification == "unrestricted"`: `http_status == 200`, `users == []`,
  `groups == []`.
- `classification == "restricted"`: `http_status == 200` and at least one user
  or group envelope exists.

`classification` is the normalized authority. Malformed normalized observations
are contract violations and fail closed.

### 3.2 Principal envelopes

A user envelope may contain only `username`, `userKey`, and `accountId`. It must
be an object, contain at least one allowed field, contain no unknown field, and
use non-empty string values. A group envelope has the exact shape
`{"name": <non-empty string>}`. Values are never trimmed or repaired during
validation.

## 4. Locked principal projection contract

Enforceable Confluence identity is deliberately narrow:

- enforceable user identity = `userKey` only;
- enforceable group identity = `group.name`.

`username` and `accountId` are never fallback enforcement identities.

For a valid enforceable user, the source representation is the exact `userKey`,
the canonical identity is `userKey.lower()`, and the ACL tag is
`"user:" + canonical_identity`. For a valid enforceable group, the source
representation is the exact `name`, the canonical identity is `name.lower()`,
and the ACL tag is `"group:" + canonical_identity`.

An enforceable identifier must be non-empty, contain no Unicode whitespace
(including NBSP), and produce a tag accepted by the active `aclTag` schema branch
(`^user:\S+$` / `^group:\S+$`). Projection never strips, normalizes Unicode,
casefolds, replaces whitespace, repairs punctuation, or falls back to another
field. It uses Python `str.lower()`, not `str.casefold()`.

Canonical identity includes the namespace: `("user", lowercase key)` and
`("group", lowercase key)` are different principals even when the textual value
is identical. When casing variants collide, the earliest exact representation is
preserved, ordered by restriction-chain order and then principal-envelope order.
Audit output is later sorted by canonical identity in M6F-B, but the earliest
occurrence decides which exact source representation survives.

M6F-A may implement the pure projection/validation helpers and immutable
projected-principal models needed by M6F-B. M6F-A must not calculate the
effective ACL intersection.

## 5. Normative M6F-B ACL policy (locked, executed later)

Even though M6F-A does not execute it, the following policy is fully locked.

### 5.1 Audit versus enforcement

- `allowed_users` / `allowed_groups` = the valid observed principal union across
  every restricted level (audit evidence).
- `acl_tags` = a separately computed deny-safe effective intersection
  (enforcement).

### 5.2 Namespace-separated intersection

Users intersect only with users; groups intersect only with groups.

### 5.3 Any unavailable observation in the chain

```
is_restricted          = true
acl_tags               = ["restricted:unresolved"]
acl_extraction_status  = "unavailable"
acl_confidence         = "approximate"
```

Omit `restriction_inherited`, `restriction_source_page_ids`, `allowed_users`,
and `allowed_groups`.

### 5.4 Complete chain with zero restricted levels

If `space_key` matches the `aclTag` space branch `^[A-Z0-9]+$`:

```
is_restricted = false
acl_tags      = ["space:<exact space_key>"]
status        = ok
confidence    = exact
```

If `space_key` is unrepresentable:

```
is_restricted = false
acl_tags      = ["restricted:unresolved"]
status        = partial
confidence    = approximate
```

`space_key` is never uppercased or repaired.

### 5.5 Complete chain with restricted levels

```
is_restricted             = true
restriction_source_page_ids = every restricted observation in chain order
restriction_inherited       = true when any restricted observation precedes the selected page
allowed_users / allowed_groups = the valid observed audit union
acl_tags                    = the effective namespace-separated intersection
```

If no effective enforceable tag remains, `acl_tags = ["restricted:unresolved"]`.

### 5.6 Status precedence and confidence

Status precedence is `unavailable > partial > ok`. Confidence is `approximate`
for `unavailable` or `partial`, and `exact` only for `ok`. Any invalid or
non-enforceable principal, or any principal removed by intersection, makes a
complete-chain result `partial` / `approximate`.

### 5.7 Invariants

Zero chunks is valid. The CanonicalDocument and RelationRecords remain
unchanged. Only `ChunkRecord.acl_tags` may change during M6F-B. ACL-only changes
never change chunk IDs, content hashes, token counts, Jira linkage, or relation
linkage.

## 6. ACLRecord omission contract (executed by M6F-B)

No JSON Schema change is required; the `ACLRecord` schema already makes the
evidence fields optional. M6F-B always reuses `acl_id =
canonical_document["acl_id"]` and `document_id =
canonical_document["document_id"]` and never regenerates a second ACL ID after
provenance validation.

An **unavailable** result emits `crawler_identity`, `is_restricted = true`,
`acl_tags = ["restricted:unresolved"]`, `acl_extraction_status = "unavailable"`,
`acl_confidence = "approximate"`, and `extracted_at`; it omits
`restriction_inherited`, `restriction_source_page_ids`, `allowed_users`, and
`allowed_groups`.

A **complete unrestricted** result emits `restriction_source_page_ids = []`,
`allowed_users = []`, `allowed_groups = []`, and `restriction_inherited =
false`.

A **complete restricted** result emits all four evidence fields, with the
allowed arrays possibly empty.

## 7. Quality reason codes (locked for M6F-B)

Deterministic reason-code order:

1. `restriction_observations_unavailable`
2. `non_enforceable_user_principal`
3. `non_enforceable_group_principal`
4. `user_principal_dropped_by_intersection`
5. `group_principal_dropped_by_intersection`
6. `empty_effective_intersection`
7. `space_tag_unrepresentable`

When `unavailable` coexists with projection problems: include `unavailable` and
the applicable projection reason codes; do **not** compute or emit
intersection-drop or empty-intersection reasons; status remains `unavailable`.
Available observations may still contribute safe observation/projection counts
when another observation is unavailable.

## 8. Quality count semantics (locked for M6F-B)

- `observed_user_envelope_occurrences`, `observed_group_envelope_occurrences`:
  occurrence counts, including duplicate and casing variants.
- `unique_valid_user_principals`, `unique_valid_group_principals`: counts of
  lowercase canonical identities in separate namespaces.
- `non_enforceable_user_occurrences`, `non_enforceable_group_occurrences`:
  occurrence counts, not unique identities.
- `user_principals_dropped_by_intersection`,
  `group_principals_dropped_by_intersection`: counts of unique canonical
  identities in separate namespaces (valid audit union minus effective
  intersection). These drop counts are zero when the chain is unavailable
  because no effective intersection is computed.

## 9. M6F metric vocabulary (locked for M6F-B)

```
acl_records_total
chunks_total
chunks_acl_changed
restriction_observations_total
available_observations
unavailable_observations
restricted_levels
unrestricted_levels
observed_user_envelope_occurrences
observed_group_envelope_occurrences
unique_valid_user_principals
unique_valid_group_principals
non_enforceable_user_occurrences
non_enforceable_group_occurrences
user_principals_dropped_by_intersection
group_principals_dropped_by_intersection
effective_users
effective_groups
default_deny_records
partial_acl_records
unavailable_acl_records
manual_review_records
```

## 10. M6F-C1 capture contract

M6F-C1 adds an opt-in mode to the existing M6B operator command. Default
behavior without the option remains: no sidecar file. With explicit capture, the
command runs the approved M6B use case, then serializes
`result.restriction_observations` directly to a deterministic UTF-8 JSON sidecar
published atomically with no-clobber semantics.

Capture output-path validation must occur before credential reading (where not
required for local validation), transport construction, adapter construction, or
any network request. An invalid, existing, repository-internal, symlink, or
symlink-parent output path causes zero network calls.

Sidecar payload:

```
{ "format_version": "1.0",
  "evidence_kind": "captured_m6b_result",
  "restriction_observations": [...] }
```

Serialization is deterministic, UTF-8 without BOM, `allow_nan=False`.
`captured_m6b_result` comes directly from
`PageObservationCollectionResult.restriction_observations`. A hand-authored
fixture is always `synthetic_fixture`. `evidence_kind` is descriptive metadata,
not cryptographic proof.

The exact serialized UTF-8 bytes, including the trailing LF, must not exceed
`MAX_RESTRICTION_SIDECAR_BYTES = 16 * 1024 * 1024` (16 MiB). This independent
artifact safety cap is shared by the M6F-C1 producer and M6F-C2 loader; it is not
derived from the per-response Confluence transport limit and does not guarantee
that every otherwise-valid M6B result is capturable. An oversized sidecar fails
closed after M6B collection without publishing a final target or rolling back
raw M6B artifacts.

Publication-failure semantics: if sidecar publication fails after M6B
collection, the command fails and the final sidecar target must not exist;
temporary sidecar cleanup is best-effort; the sidecar writer must not modify,
delete, or roll back raw M6B artifacts; raw restriction/attachment artifacts
already written successfully by M6B remain preserved. The contract does not
assert the entire raw tree is unchanged across a live M6B rerun.

Implementation, review, and tests for C1 are offline using fake transports. One
separately authorized controlled live read-only M6B run is allowed later to
create real evidence.

## 11. Future M6F-C2 acceptance contract (document only)

M6F-C2 is offline. It loads a strict bounded sidecar, binds its full ordered
`source_page_id` sequence to `extract_ordered_restriction_targets()` from
preserved M6A raw bytes, runs M6F composition without network, and supports
synthetic and captured evidence explicitly.

The safe CLI success summary always includes `restriction_evidence_kind` and
`real_captured_evidence`. For synthetic input, `restriction_evidence_kind =
"synthetic_fixture"` and `real_captured_evidence = false`. For accepted real
captured input, `restriction_evidence_kind = "captured_m6b_result"` and
`real_captured_evidence = true`.

Final real M6F closeout may pass only when `restriction_evidence_kind ==
"captured_m6b_result"` and `real_captured_evidence == true`. This prevents a
synthetic acceptance run from being mistaken for a real captured-evidence
acceptance. The field is still not cryptographic proof.

## 12. Failure taxonomy

M6F failures are sanitized, category-tagged, and carry only the stable category
in their message. Exception messages never expose page IDs; document, chunk,
relation, or ACL IDs; Jira keys; principal identifiers; titles; content; hashes;
paths; URLs; or crawler identity.

The complete later-stage category vocabulary is:

```
canonical_document_invalid
chunk_record_invalid
canonical_chunk_identity_mismatch
acl_stage_input_not_pristine
m6e_relation_provenance_invalid
m6e_result_provenance_invalid
invalid_restriction_observations
canonical_observation_identity_mismatch
invalid_crawler_identity
invalid_extracted_at
acl_materialization_failed
```

M6F-A implements only the categories relevant to its delivered validators and
models: `canonical_document_invalid`, `chunk_record_invalid`,
`canonical_chunk_identity_mismatch`, `acl_stage_input_not_pristine`,
`m6e_relation_provenance_invalid`, `m6e_result_provenance_invalid`,
`invalid_restriction_observations`, `canonical_observation_identity_mismatch`,
and the wrapper `acl_materialization_failed`. `invalid_crawler_identity` and
`invalid_extracted_at` are reserved for M6F-B `ACLRecord` construction.

M6F-C1 operator failures use a separate CLI/infrastructure vocabulary rather
than extending the ACL materialization domain taxonomy:

```
sidecar_target
sidecar_serialization
sidecar_publication
```

They map respectively to invalid preflight target, deterministic
serialization/size-limit failure, and post-collection publication failure.
