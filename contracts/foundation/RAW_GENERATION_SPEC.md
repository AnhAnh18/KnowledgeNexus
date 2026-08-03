# Confluence Raw Generation Specification (M7-A3b)

## 1. Status, authority, and scope

Status: M7-A3b contract complete and owner-approved. The full M7 roadmap is
owner-authorized for bounded stage implementation; each raw-generation stage
still requires its own reviewed plan, validation, and independent gate.

This specification narrows `CRAWL_RELIABILITY_SPEC.md` owner decisions C, D,
and H. It is authoritative for future M7 raw-generation isolation,
restriction-evidence serialization, replay/orphan recovery, writer ownership,
and raw-storage budgets.

The broader specification remains contract authority and does not itself
define stage completion. M7 implementation may add live crawl, lock,
checkpoint, request, retry, budget, attachment, and replay behavior only within
the separately reviewed roadmap stages. No stage may migrate or reinterpret M6
raw artifacts without an explicit scoped contract decision.

```text
M7-A2: COMPLETE AND APPROVED
M7-A3a: COMPLETE AND APPROVED
M7-A3b: COMPLETE AND APPROVED
M7-CONTRACT-GATE: APPROVED
M7 production implementation: OWNER-AUTHORIZED BY BOUNDED STAGES
```

## 2. Generation ownership

For M7-v1, when raw generation is later activated, the raw-generation identity
equals the system-generated `run_id`; there is no independent caller-supplied
generation ID.

One crawl run owns exactly one immutable raw generation. The conceptual
namespace is:

```text
raw/
  confluence/
    generations/
      <run_id>/
        pages/
        restrictions/
        attachment_metadata/
```

This layout is conceptual. Production filenames and APIs remain later
implementation decisions.

Rules:

- a generation belongs to one run and no other run;
- a new crawl run uses a new generation;
- published generation artifacts are immutable;
- there is no raw `LATEST.txt`;
- M3 snapshot publication semantics do not apply to raw crawl generations;
- existing M6A/M6B fixed-path artifacts are not migrated, replaced, or
  reinterpreted as M7 evidence.

## 3. Logical artifact identity

Each artifact family has an immutable storage key. The observed body/status is
evidence bound to that key, not a second key that allows conflicting evidence to
coexist within one run:

### Raw page

```text
run identity
page identity
request-profile version
source version when available
```

### Restriction observation

```text
run identity
selected page identity
target page identity
request-profile version
```

The observed HTTP status and exact body bytes are evidence fields for this
storage key. A different status or body under the same key is a `state_conflict`.

### Attachment-metadata window

```text
run identity
page identity
requested start
requested limit
request-profile version
```

Exact body bytes are evidence for this storage key. Different evidence under the
same key is a `state_conflict`.

An artifact path or checkpoint reference MUST bind to its storage key and
evidence. Path/envelope disagreement is a state conflict, not a reason to
repair or rename evidence automatically.

## 4. Same-run replay

For one storage key:

| Existing state | Required action |
| --- | --- |
| Destination absent | Publish atomically after validation and budgets |
| Published artifact present and canonical bytes identical | Validate identity, then reuse |
| Published artifact present but bytes differ | `state_conflict` |
| Published artifact present but parse/identity validation fails | Fail closed |
| Temporary/partial artifact only | Do not treat it as published evidence |

Published artifacts MUST NOT be overwritten. In particular, future M7 stores
MUST NOT use replacement semantics over an existing generation artifact.

Identical means byte-identical canonical artifact bytes, not merely equivalent
decoded JSON objects.

## 5. Restriction-evidence envelope

The version-1 envelope contains exactly these fields:

```text
format_version
evidence_kind
request_kind
request_profile_version
selected_page_id
target_page_id
http_status
body_encoding
body_base64
body_byte_count
body_sha256
```

Fixed values:

```text
format_version = "1"
evidence_kind = "confluence_restriction_observation"
request_kind = "view_restriction"
body_encoding = "base64"
```

No additional field is allowed in format version 1. Identity fields MUST use
the approved Confluence page-ID grammar. `http_status` MUST be an integer, not
a boolean.

## 6. Canonical serialization

The envelope uses:

```text
UTF-8 JSON
object keys sorted
compact separators
ensure_ascii = false
allow_nan = false
no BOM
no trailing newline
```

Serialized output MUST be deterministic for the same inputs. A decoder MUST
reject duplicate JSON object keys, non-object roots, missing/extra fields,
noncanonical fixed values, booleans where integers are required, and values
outside their field contracts.

An existing envelope whose bytes are not the canonical reserialization of its
validated value is invalid M7 evidence. It MUST NOT be silently normalized or
rewritten in place.

## 7. Exact body-byte representation

`body_base64` uses the standard RFC 4648 base64 alphabet with required
padding. Decoding is strict:

- whitespace is rejected;
- non-alphabet characters are rejected;
- missing or invalid padding is rejected;
- URL-safe alphabet substitutions are rejected.

Validation is:

```text
decoded_body = strict_base64_decode(body_base64)
len(decoded_body) == body_byte_count
lowercase_hex(SHA-256(decoded_body)) == body_sha256
```

Count and hash are computed over the exact decoded original response bytes,
not the JSON envelope or base64 text. Empty bodies are valid and have a count
of zero.

## 8. Restriction status semantics

Only these statuses may form completed restriction evidence:

```text
200
401
403
404
```

Operational retry statuses:

```text
408
429
500
502
503
504
```

follow `RETRY_POLICY_SPEC.md` and MUST NOT be materialized as restriction
observations.

Every other status is terminal unless a future reviewed focused contract
explicitly allows it. Same body bytes with a different HTTP status are
different evidence and MUST conflict under the same logical target.

## 9. Atomic no-clobber publication

Future publication MUST provide these properties:

1. Validate logical identity and serialize the complete canonical artifact.
2. Check projected byte, artifact-count, and free-disk budgets.
3. Write a complete temporary artifact in the same filesystem/publication
   domain.
4. Apply the implementation's reviewed flush/durability barrier.
5. Publish atomically only when the destination is absent.
6. If the destination exists, bounded-read and validate it before deciding
   identical reuse versus conflict.
7. Never overwrite the destination.
8. Never treat temporary residue as committed evidence.
9. Advance no checkpoint until publication and required validation succeed.

The implementation mechanism is intentionally unspecified, but it MUST prove
atomic no-clobber behavior under concurrent-creator tests. A separate
existence check followed by replace is insufficient.

## 10. Orphan recovery

An orphan is a published artifact whose associated checkpoint transition did
not commit.

Resume handles it in this order:

```text
bounded-read existing artifact
→ parse canonical envelope
→ validate exact required fields
→ strict base64 decode
→ validate byte count and body hash
→ validate run/request/page/profile binding
→ rebuild the status-aware observation
→ perform downstream validation
→ commit the checkpoint without refetch
```

An invalid orphan:

- is not overwritten;
- is not automatically deleted;
- never has status inferred from its body;
- never becomes an unavailable/unrestricted observation by default;
- fails closed and may require separately authorized operator recovery.

Existing M6 body-only restriction artifacts lack the status/envelope binding
and are insufficient for this M7 orphan-recovery path.

## 11. Raw page and attachment-window contracts

M7-A3b does not require the restriction envelope format for other artifact
families, but each future format MUST preserve and validate its full logical
binding from §3.

For raw pages:

- exact response bytes are preserved;
- page/request identity is validated;
- source version is retained when available;
- a missing source version never proves unchanged content.

For attachment-metadata windows:

- exact response bytes are preserved;
- requested start and limit are bound;
- page and request-profile identity are bound;
- pagination parsing occurs before checkpoint advancement.

### 11.1 Raw-page envelope version 1

The D3 raw-page envelope contains exactly these fields:

```text
format_version
evidence_kind
request_kind
request_profile_version
run_id
generation_id
page_id
source_version
http_status
body_encoding
body_base64
body_byte_count
body_sha256
```

Fixed values are:

```text
format_version = "1"
evidence_kind = "confluence_raw_page"
request_kind = "page_body"
request_profile_version = "m7-confluence-request-profile-v1"
body_encoding = "base64"
```

`run_id` and `generation_id` are canonical lowercase UUIDv4 strings and MUST
be equal for M7-v1. `page_id` uses the strict ASCII decimal page-ID grammar.
`source_version` is either JSON `null` or a non-empty string of at most 256
characters without control characters. A missing source version never proves
unchanged content or permits cross-run reuse. `http_status` is an integer from
100 through 599; booleans and values outside that range are invalid.

The canonical serialization is UTF-8 JSON with sorted object keys, compact
separators, `ensure_ascii=false`, `allow_nan=false`, no BOM, and no trailing
newline. Base64 decoding is strict. `body_byte_count` and `body_sha256` are
computed over the exact decoded response bytes; empty bodies are valid. Any
noncanonical, duplicate-key, missing-field, extra-field, identity, count, hash,
or path mismatch fails closed and is never rewritten in place.

The D3 path is:

```text
raw/confluence/generations/<run_id>/pages/<page_id>.json
```

The logical key is `(run_id, page_id, request_profile_version, source_version)`
with the path binding the run and page components. Identical canonical bytes
under the same path are reusable. Any differing body, status, profile, or
source version is a same-run replay conflict. A different run always uses a
different generation path. D3 does not implement cross-run reuse, retention,
checkpoint advancement, budgets, or orphan recovery.

## 12. Cross-run reuse

A raw page artifact from an earlier generation may be referenced, not copied
or mutated, only when all hold:

- source version is present and equal;
- endpoint/source fingerprint is equal;
- request-profile version is equal;
- raw-layout contract version is equal;
- artifact bytes and identity were validated;
- the source generation remains retention-pinned.

Restriction and attachment observations MUST NOT be skipped or reused solely
because the page source version is unchanged.

Cross-run reuse creates a durable retention dependency. A pinned generation
MUST NOT be automatically deleted.

## 13. Process-lifetime writer lock

The future writer uses one exclusive process-lifetime OS file lock:

- ownership is the live OS handle, not file contents;
- acquisition fails fast while another writer owns the lock;
- there is no TTL or timestamp lease;
- there is no heartbeat expiry;
- there is no automatic stale takeover;
- process termination releases the live lock handle;
- a leftover lock file does not prove an active writer;
- after acquiring the lock, an unfinished run is recorded as an interrupted
  previous session before resuming an active raw-generation phase.

An M7-C inventory-complete no-op resume does not activate a raw-generation phase
and creates no interrupted-session record or checkpoint mutation.

The lock scope and checkpoint scope MUST be identical. A lock implementation
must reject symlink/reparse/path-redirection hazards under the focused M7-C
checkpoint-store contract. Future raw-generation work reuses that lock boundary
and must not select a competing platform library.

## 14. Raw-storage budgets

The exact limits come only from `crawl_reliability_profile.yaml`:

```text
max_raw_bytes_per_run
max_raw_artifacts_per_run
minimum_free_disk_reserve_bytes
```

Before publication, using the complete serialized artifact size:

```text
projected_raw_bytes <= max_raw_bytes_per_run
projected_artifact_count <= max_raw_artifacts_per_run
projected_free_disk_after_write >= minimum_free_disk_reserve_bytes
```

All inequalities must hold. Otherwise:

```text
raw_storage_budget_exhausted
no artifact publication
no checkpoint advancement
no generation completion/activation
```

Budget counters advance only for newly published artifacts, not identical
reuse. Temporary bytes are included in free-space safety calculations.

M7 performs no automatic generation deletion. Retention and operator cleanup
remain separately reviewed operational work.

## 15. Failure and security boundary

Raw-store diagnostic failure categories include:

```text
raw_artifact_invalid
raw_identity_mismatch
raw_replay_conflict (diagnostic alias for state_conflict)
raw_storage_budget_exhausted
raw_publication_failure
writer_active
writer_lock_failure
```

They MUST NOT disclose raw exception messages or sensitive values.

`raw_replay_conflict` is a raw-store diagnostic label only. Any result crossing
the M7 retry/outcome boundary MUST normalize every raw identity, evidence,
path, or replay conflict to `state_failure/state_conflict` with zero retry as
defined by `RETRY_POLICY_SPEC.md`. It MUST NOT emit `raw_replay_conflict` as a
second stable outcome kind.

Logs, Git evidence, `str`, and `repr` MUST NOT include:

```text
response body or body_base64
body_sha256
HTTP status tied to a real target
real page/source/principal identity
raw artifact path
endpoint or credential
full crawl fingerprint
```

Allowed sanitized evidence is limited to allowlisted artifact kind,
publication/reuse outcome, validation booleans, aggregate counts, and stable
failure category.

## 16. Deterministic acceptance matrix

| ID | Required case and result |
| --- | --- |
| `A3B-ENV-01` | Status 200 body round-trips exact bytes |
| `A3B-ENV-02` | Status 404 empty body round-trips exact bytes |
| `A3B-ENV-03` | Strict base64 failure is rejected |
| `A3B-ENV-04` | Byte-count mismatch is rejected |
| `A3B-ENV-05` | Body-hash mismatch is rejected |
| `A3B-ENV-06` | Path/envelope identity mismatch fails closed |
| `A3B-ENV-07` | Same body with different status conflicts |
| `A3B-ENV-08` | Noncanonical JSON is rejected without rewrite |
| `A3B-ENV-09` | Extra/missing/duplicate field is rejected |
| `A3B-PAGE-ENV-01` | Raw-page envelope preserves empty and arbitrary body bytes |
| `A3B-PAGE-ENV-02` | Run/generation/page/profile/source identity mismatch fails closed |
| `A3B-PAGE-ENV-03` | Invalid status, source version, count, or hash is rejected |
| `A3B-PAGE-ENV-04` | Raw-page canonical serialization round-trips exactly |
| `A3B-PAGE-RAW-01` | Absent raw-page artifact publishes atomically |
| `A3B-PAGE-RAW-02` | Identical same-run raw-page replay reuses evidence |
| `A3B-PAGE-RAW-03` | Differing same-run raw-page evidence conflicts |
| `A3B-PAGE-RAW-04` | Distinct generation publishes to a distinct path |
| `A3B-PAGE-RAW-05` | Malformed, partial, non-regular, or redirected target fails closed |
| `A3B-PAGE-RAW-06` | Concurrent identical/different creators cannot overwrite |
| `A3B-RAW-01` | Absent artifact publishes atomically |
| `A3B-RAW-02` | Identical same-run replay reuses evidence |
| `A3B-RAW-03` | Differing same-run replay fails closed |
| `A3B-RAW-04` | Valid orphan commits checkpoint without refetch |
| `A3B-RAW-05` | Invalid orphan fails without overwrite/delete |
| `A3B-RAW-06` | New-run changed evidence is accepted in a new generation |
| `A3B-RAW-07` | Reused page pins the referenced generation |
| `A3B-RAW-08` | Page version alone never reuses restrictions |
| `A3B-LOCK-01` | Active writer causes immediate failure |
| `A3B-LOCK-02` | Process crash releases live handle |
| `A3B-LOCK-03` | Leftover lock file does not imply active writer |
| `A3B-LOCK-04` | Ambiguous durable run state fails closed |
| `A3B-BUDGET-01` | Byte cap fails before publication |
| `A3B-BUDGET-02` | Artifact cap fails before publication |
| `A3B-BUDGET-03` | Free-disk reserve fails before publication |
| `A3B-BUDGET-04` | Retention-pinned generation cannot be deleted |

Future tests MUST also force concurrent destination creation, partial
temporary writes, failures at every publication boundary, and deterministic
canonical serialization.

## 17. Review gate

An independent reviewer must confirm:

- status and exact body bytes are sufficient for orphan replay;
- serialization and strict base64 preserve bytes without ambiguity;
- no-clobber is atomic and excludes replacement of published evidence;
- existing M6 artifacts remain unchanged and insufficient for M7 replay;
- retryable operational statuses never become ACL observations;
- lock ownership has no TTL takeover;
- storage failures occur before publication/checkpoint advancement;
- each stage remains within its reviewed boundary and does not claim later
  checkpoint, budget, lock, attachment, retention, migration, or network gates
  before those stages are independently approved.

Recorded integrated review state:

```text
M7-CONTRACT-GATE: APPROVED
M7-D3 raw-page store: COMPLETE AND INDEPENDENTLY REVIEWED
M7-D later stages: OWNER-AUTHORIZED BY FOCUSED PLAN/GATE
```
