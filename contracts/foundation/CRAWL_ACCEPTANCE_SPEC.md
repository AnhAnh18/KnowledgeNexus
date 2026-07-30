# Crawl Fingerprint and Acceptance Specification (M7-A3c)

## 1. Status, authority, and scope

Status: contract-only M7-A3c contract complete and owner-approved.

```text
M7-A1: OWNER-APPROVED
M7-A1 independent review: WAIVED BY OWNER
M7-A2: COMPLETE AND APPROVED
M7-A3a: COMPLETE AND APPROVED
M7-A3b: COMPLETE AND APPROVED
M7-A3c: COMPLETE AND APPROVED
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```

The owner explicitly authorized stacked A2/A3 contract drafting before the
later integrated independent review. This authorization does not approve any
candidate and does not authorize production work.

This specification narrows `CRAWL_RELIABILITY_SPEC.md` owner decisions J and
K. It is authoritative for crawl-fingerprint construction, controlled-stop
semantics, and M7 offline/live acceptance gates.

It contains no fingerprint builder, clock, sleeper, crawler, checkpoint store,
network call, live run, or production test.

## 2. Fingerprint ownership and timing

The crawl fingerprint is produced only by a trusted builder from validated
effective configuration. A caller provides configuration inputs, never a
digest or precomputed fingerprint.

Fingerprint construction occurs:

```text
after configuration/profile validation
before the first network request
before checkpoint or raw-generation mutation
before run discovery or creation is committed
```

Resume requires exact fingerprint equality. Mismatch fails closed before any
request or durable state mutation. The builder MUST NOT accept an override,
fallback, or caller-supplied digest.

## 3. Endpoint canonicalization

The endpoint identity is derived from:

```text
scheme
normalized_host
effective_port
normalized_rest_base_path
```

Rules:

- scheme MUST be `https` and is canonicalized lowercase;
- host is converted to IDNA ASCII, lowercased, and stripped of one trailing
  DNS dot;
- host MUST be non-empty;
- omitted port means effective decimal port `443`;
- an explicit port MUST be numeric and valid;
- REST base-path case is preserved;
- an empty REST base path becomes `/`;
- one or more trailing slashes are removed except when the result is `/`;
- user-info, query, fragment, whitespace, and control characters are rejected.

The preimage is:

```text
UTF-8(
    scheme
    + "\x1f"
    + normalized_host
    + "\x1f"
    + decimal_effective_port
    + "\x1f"
    + normalized_rest_base_path
)
```

Only this value is persisted:

```text
endpoint_identity_sha256 =
    lowercase_hex(SHA-256(preimage))
```

The raw URL, raw hostname, base path, and preimage MUST NOT be persisted in
checkpoint rows, emitted in logs/evidence, or included elsewhere in the crawl
fingerprint object.

## 4. Crawl fingerprint object

The version-1 object contains exactly these required fields.

### String fields

```text
fingerprint_contract_version
deployment_api_family
request_profile_version
endpoint_identity_sha256
space_key
scope_policy_version
scope_config_digest
query_shape_profile_version
expand_shape_profile_version
reliability_profile_id
reliability_profile_version
mapper_contract_version
raw_layout_contract_version
foundation_schema_version
chunking_contract_version
jira_relation_contract_version
acl_contract_version
```

Digest fields are lowercase SHA-256 hex strings. Version/profile fields are
non-empty strings. `space_key` follows the approved source-config contract.

### Canonically sorted string-array fields

```text
include_root_page_ids
excluded_subtree_page_ids
```

Each array contains unique validated page-ID strings sorted by canonical
string order. Operator input order is not retained.

### Non-negative integer fields

```text
inventory_page_size
attachment_page_size
max_include_roots
max_pages_per_run
max_inventory_windows_per_root
max_inventory_windows_per_run
max_restriction_targets_per_page
max_restriction_observations_per_run
max_attachment_windows_per_page
max_attachment_windows_per_run
max_total_requests_per_run
max_response_bytes_per_request
max_raw_bytes_per_run
max_raw_artifacts_per_run
minimum_free_disk_reserve_bytes
```

Every integer uses the exact effective value from the validated reliability
profile; booleans are invalid integers. Fields whose active profile contract
requires positivity remain positive.

All fields are required in version 1. There are no optional or boolean
fingerprint fields in version 1. Missing, extra, null, non-finite, or
wrong-typed values fail before hashing.

## 5. Canonical fingerprint serialization

The fingerprint object uses:

```text
UTF-8 JSON
object keys sorted
compact separators
ensure_ascii = false
allow_nan = false
no BOM
no trailing newline
all required keys present
no additional keys
```

The page-ID arrays are sorted and duplicate-free before serialization.
Semantically ordered values MUST NOT be sorted unless their field contract
explicitly declares order irrelevant. Version 1 has no optional fields; a
future approved optional field that is unavailable MUST be represented as
explicit `null`, not omitted.

The final value is:

```text
crawl_fingerprint =
    lowercase_hex(SHA-256(canonical_json_bytes))
```

Equivalent validated configuration produces identical bytes and digest.
Every fingerprint-relevant change produces a different digest.

## 6. Scope configuration digest

`scope_config_digest` is itself trusted-builder output over the complete
approved M5 scope configuration that is not represented directly by
`space_key`, include roots, exclusions, and `scope_policy_version`.

Its canonicalization MUST be separately versioned by
`scope_policy_version`, deterministic, secret-free, and independent of
operator input ordering where order has no semantic meaning. Callers MUST NOT
supply this digest directly.

Changing include roots, exclusions, scope policy/config, or their version
changes the crawl fingerprint.

## 7. Excluded fingerprint inputs

The fingerprint and all nested digest preimages MUST exclude:

```text
credential or token
username
raw URL
raw hostname or base path
source ID
raw query or CQL text
local filesystem path
run ID
process-session ID
controlled-stop policy
session timeout
log verbosity
acceptance phase label
machine identity
```

Exclusion from the fingerprint does not authorize logging or persistence.
Security rules in the other focused contracts still apply.

## 8. Controlled-stop input

Controlled stop is an optional process-session policy:

```text
stop_after:
  checkpoint_kind: <allowlisted kind>
  committed_count: N
```

Allowlisted kinds:

```text
inventory_window_committed
raw_page_committed
restriction_target_committed
attachment_window_committed
page_acquisition_complete
```

`committed_count` MUST be a positive integer and not a boolean. Unknown kinds,
zero/negative counts, missing fields, and extra fields fail before work.

The policy belongs to the process session and is excluded from the crawl
fingerprint.

## 9. Controlled-stop transition

For the selected kind:

```text
perform work
→ commit the corresponding checkpoint transaction
→ confirm commit success
→ increment the session-local committed counter
→ evaluate threshold
→ if reached, pause before any next network request
```

Rolled-back transitions, retry attempts, sleeps, raw inspection, parsing,
temporary-file creation, and nonmatching checkpoint kinds do not increment
the counter.

When the threshold is reached:

- no next network request starts;
- no new checkpoint transaction starts;
- durable stores close cleanly;
- the writer lock is released;
- the crawl run remains incomplete and resumable;
- session outcome is exactly:

```json
{"status":"paused","reason":"controlled_checkpoint_stop"}
```

Exit code zero is allowed, but an operator/runbook MUST inspect the semantic
status. `paused` MUST NOT be reported as `complete` or `success`.

## 10. Offline acceptance boundary

M7 offline acceptance uses no network, credentials, real endpoint, real page
identity, or production artifact.

The future harness contains:

```text
scripted fake transport
fake injected UTC clock
fake monotonic clock
fake sleeper
temporary raw store
temporary metadata store
deterministic fault injector
child-process RSS observer
```

The harness MUST combine:

- all A2 retry/Retry-After/rate/budget cases;
- all A3a run, crash, pagination, and overlapping-root cases;
- all A3b envelope, no-clobber, orphan, lock, and storage-budget cases;
- fingerprint determinism and sensitivity;
- controlled stop and resume;
- bounded scale and memory methodology.

Two executions with the same scripted inputs MUST produce identical
decisions, requests, sleeps, checkpoints, raw tree, normalized page set, and
sanitized counters.

## 11. Scale methodology

The future offline scale gate uses:

```text
functional corpus: 10,000 inventory pages
extended corpus: 100,000 inventory pages
inventory page size: active profile value
crash injection: every window/commit boundary
RSS sampling: child process at a fixed periodic interval
baseline RSS: after runtime initialization, before corpus processing
reported growth: peak RSS minus baseline RSS
```

The gate verifies:

- exact final normalized page set;
- no duplicate final page IDs;
- exact bounded request/window counts;
- resume equivalence with uninterrupted execution;
- no orchestrator whole-corpus materialization;
- deterministic state/output between repeated runs;
- memory-growth comparison between functional and extended workloads.

The absolute RSS threshold is intentionally not invented here. The owner MUST
lock it after a reproducible baseline and before the M7 scale implementation
gate is approved.

## 12. Offline fault-injection points

The future integrated suite injects failure at least:

```text
before request
after response
during raw temporary write
after raw publication
before checkpoint transaction
during inventory row insertion
after rows but before cursor mutation
after checkpoint commit before acknowledgement
between inventory windows
between restriction targets
between attachment windows
at controlled-stop threshold
```

For every point, resumed final state MUST equal uninterrupted final state or
fail closed with the contract's stable category. No fault path may silently
overwrite evidence or advance a cursor without its rows/artifact.

## 13. Controlled live acceptance gate

No live execution is performed or authorized by M7-A3c. A later live gate
requires separately authorized phases:

```text
L2-PRE  static preflight
L2-1    one authorized bounded controlled-stop crawl
L2-2    offline post-stop inspection
L2-3    one separately authorized resume
L2-4    bounded completion
L2-5    durable readback
L2-6    sanitized security scan
L2-7    clean tracked worktree and local provenance
```

The live gate MUST use an approved transferred execution tree and repository-
local provenance under `REPOSITORY_TRANSFER_POLICY.md`. Foreign Git SHAs are
not checkout requirements.

## 14. Live prohibitions

The live acceptance MUST NOT:

- use Ctrl+C, timed kill, random failure, or network disconnect as the
  controlled-stop mechanism;
- intentionally force HTTP 429 or server failures;
- retry a failed operator invocation merely to probe behavior;
- activate an incomplete generation;
- publish a Foundation export snapshot without separate authorization;
- commit raw generations, checkpoint databases, request traces, logs, or
  credentials;
- emit real paths, endpoint, IDs, content, principals, or full hashes in
  durable evidence.

Retry/fault correctness belongs to the offline scripted gate, not live fault
induction.

## 15. Sanitized acceptance evidence

Durable evidence may contain:

```text
milestone/gate ID
authorization booleans
aggregate counts
stable outcome/failure categories
checkpoint and resume gate booleans
determinism and boundedness booleans
tracked-worktree result
transfer-equivalence result
```

It MUST NOT contain:

```text
raw/source URL or endpoint components
credential or credential-shaped value
real run/page/source/principal identity
raw response or normalized content
raw-generation/checkpoint/evidence path
full crawl/body/artifact hash
machine identity
foreign SHA as a portable completion requirement
```

## 16. Fingerprint acceptance matrix

| ID | Required case and result |
| --- | --- |
| `A3C-FP-01` | Same effective config in different input order yields same digest |
| `A3C-FP-02` | Default and explicit effective HTTPS port yield same endpoint digest |
| `A3C-FP-03` | Host case and one trailing dot normalize identically |
| `A3C-FP-04` | REST base-path case remains significant |
| `A3C-FP-05` | User-info/query/fragment is rejected |
| `A3C-FP-06` | Duplicate include/exclude ID is rejected |
| `A3C-FP-07` | Every required field missing/wrong type is rejected |
| `A3C-FP-08` | Extra or null field is rejected in version 1 |
| `A3C-FP-09` | Meaningful scope/profile/version change changes digest |
| `A3C-FP-10` | Session controls/log settings do not change digest |
| `A3C-FP-11` | Resume mismatch fails before request/mutation |
| `A3C-FP-12` | Caller-supplied digest override is rejected |

## 17. Controlled-stop and integrated acceptance matrix

| ID | Required case and result |
| --- | --- |
| `A3C-STOP-01` | Invalid kind/count fails before work |
| `A3C-STOP-02` | Rolled-back transition does not increment |
| `A3C-STOP-03` | Nonmatching checkpoint kind does not increment |
| `A3C-STOP-04` | Threshold is evaluated only after commit |
| `A3C-STOP-05` | Pause starts no next request and releases lock |
| `A3C-STOP-06` | Paused run remains incomplete and resumable |
| `A3C-STOP-07` | Resume completes without duplicate transition |
| `A3C-STOP-08` | Stop policy change does not alter fingerprint |
| `A3C-OFF-01` | Fake-clock/sleeper replay is deterministic |
| `A3C-OFF-02` | Every crash point matches uninterrupted state |
| `A3C-OFF-03` | 10k and 100k corpora produce exact bounded results |
| `A3C-OFF-04` | Memory comparison uses child-process delta RSS |
| `A3C-LIVE-01` | Every live phase requires its stated authorization |
| `A3C-LIVE-02` | Durable evidence passes the sanitized boundary |

## 18. Integrated review gate

The reviewer must inspect A1, A2, A3a, A3b, and A3c together and confirm:

- one authority and one name exists for each concept;
- fingerprint fields/canonicalization are complete and secret-free;
- equivalent configurations have identical digests;
- meaningful configuration changes have different digests;
- run/session controls are excluded correctly;
- controlled stop occurs only after a committed transition;
- paused is never mistaken for complete;
- offline scale/fault methodology is reproducible;
- live phases require separate authorization;
- no contract changes M5/M6 schemas or semantics;
- no source/test/schema implementation exists.

## 19. Contract completion state

The owner approved the complete M7-A2/A3 contract stack:

```text
M7-A1: OWNER-APPROVED
M7-A1 independent review: WAIVED BY OWNER
M7-A2: COMPLETE AND APPROVED
M7-A3a: COMPLETE AND APPROVED
M7-A3b: COMPLETE AND APPROVED
M7-A3c: COMPLETE AND APPROVED
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```

The approved contract gate opens production implementation planning only.
Production code remains unauthorized until a later plan is reviewed and the
owner separately authorizes implementation.
