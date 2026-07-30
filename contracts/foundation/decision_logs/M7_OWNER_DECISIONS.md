# M7 Owner Decisions — Crawl Reliability and Scale

Status block:

```text
M7 owner decisions: LOCKED
M7-A1: OWNER-APPROVED
M7-A1 independent review: WAIVED BY OWNER
M7-A2: COMPLETE AND APPROVED
M7-A3a: COMPLETE AND APPROVED
M7-A3b: COMPLETE AND APPROVED
M7-A3c: COMPLETE AND APPROVED
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```

This document records the owner-locked M7 decisions for the M7-A1 contract
draft. It distinguishes approved prior facts, owner-locked M7 decisions,
deferred implementation choices, and unresolved operational items. It is a
decision record, not a design or implementation specification; the companion
`CRAWL_RELIABILITY_SPEC.md` defines the normative contract shape.

Precedence: `contracts/foundation/schemas/` and the active focused specs
(`CHUNKING_SPEC.md`, `JIRA_RELATION_SPEC.md`, `ACL_MATERIALIZATION_SPEC.md`,
`ONE_PAGE_EXPORT_SPEC.md`, `CRAWL_RELIABILITY_SPEC.md`, and
`RETRY_POLICY_SPEC.md` with `crawl_reliability_profile.yaml`) remain unchanged
and continue to win every field-level dispute. Nothing in this document
overrides approved M5/M6 semantics; §3 records only additive M7 reliability
decisions.

## 1. Approved prior facts

- M6A through M6G-D are complete and approved. The one-page Foundation
  vertical slice has real raw provenance, deterministic normalization and
  chunking, Jira relations, deny-safe ACL materialization, and one published
  full-snapshot export through the approved M3 path.
- M7-A1 is owner-approved, with its independent review explicitly waived by
  the owner. The owner subsequently approved the complete M7-A2 and M7-A3
  contract stack and the aggregate M7 contract gate.
- M7 production implementation is **not authorized** by this document or by
  any document it references. M7-A1 through M7-A3 authorize contract
  artifacts only.
- Durable cross-repository state uses milestone IDs and gate outcomes, not
  shared commit SHAs, per the existing repository transfer policy. This
  document introduces no commit SHA and no machine-local path.

## 2. Owner-locked M7 decisions

The following decisions are locked for the M7 contract draft. Detailed
mechanics explicitly deferred to a later task are named at the end of each
item and are not resolved here.

### A. Pagination authority

Approved M5B pagination behavior is preserved unchanged. Each descendants
response window is evaluated against its own observed `totalSize`; drift in
`totalSize` between windows is permitted and is recorded, not rejected or
frozen. No `expected_total_size` value is fixed for a crawl. Confluence
`_links.next` is not pagination authority and never determines the next
request or the terminal state. The next window start is computed as
`next_start = response.start + response.size`, and a window is terminal when
`next_start >= response.totalSize`. M7 guarantees crash consistency for
inventory persistence; it does not claim an upstream point-in-time inventory
snapshot.

### B. Inventory durability

Normalized inventory occurrences and cursor/terminal state will be persisted
together in one future SQLite transaction. No durable cursor advancement may
occur without all rows for that window having been durably persisted in the
same transaction. M7-A1 does not define SQLite DDL, table shapes, or column
names; that belongs to a later reviewed task.

### C. Raw evidence

Future M7 raw artifacts are immutable and scoped to exactly one crawl run and
generation. Identical replay of the same evidence within the same run is
accepted. Differing evidence observed within the same run for the same
logical target is a state conflict, not a silent overwrite. A new crawl run
may preserve changed evidence under a new generation. Existing M6 fixed-path
raw artifacts (the M6A raw page store and M6B restriction/attachment
observation stores) remain unchanged by this decision; M7 generations are
additive and do not retrofit or reinterpret the M6 fixed-path convention.

### D. Single writer

Crawl-run ownership uses a process-lifetime exclusive OS file lock. There is
no timestamp-based lease, no time-to-live takeover, and no automatic
stale-lock takeover of any kind.

### E. Run and session

A crawl run is the durable unit that owns fingerprint, generation, inventory
state, and checkpoint state. A process session is the unit that owns the OS
lock and session-level controls (including controlled stop, §2.J). One crawl
run may span multiple process sessions.

### F. Run operations

Exactly three mutually exclusive run operations exist:

1. `start_new_run`
2. `resume_explicit_run_id`
3. `resume_unique_incomplete_run`

There is no fallback path between these three operations. A
`resume_unique_incomplete_run` request that matches zero incomplete runs
fails closed. A request that matches more than one incomplete run also fails
closed; the newest matching run is never selected automatically. Starting a
new run must never silently ignore an existing incomplete run that shares the
same fingerprint — that condition is a caller-visible conflict, not a
silent skip.

### G. Overlapping include roots

Overlapping include roots remain supported, unchanged from approved M5A/M5B
behavior. Inventory occurrences are persisted per include root, so the same
descendant page may legitimately appear once per overlapping root with
different root-relative ancestor paths. Final cross-root compatibility is
compared as ordered pairs of `(ancestor_page_id, ancestor_title)`, never by
ID alone. The detailed deduplication mechanics belong to a later task
(M7-A3a).

### H. Restriction evidence

A future M7 generation-scoped restriction-evidence artifact will use one
immutable versioned envelope that contains both the observed HTTP status and
the exact response body bytes. Existing M6 body-only restriction artifacts
remain unchanged by this decision and are not, on their own, sufficient
evidence for M7 orphan replay. The exact envelope serialization belongs to a
later task (M7-A3b).

### I. Retry direction

Retryable HTTP statuses are exactly `408`, `429`, `500`, `502`, `503`, and
`504`; no other status is retryable. `max_attempts` includes the initial
attempt (it is not "initial attempt plus N retries"). A valid `Retry-After`
value that exceeds the configured single-delay policy limit terminates retry
outright — it is never clamped downward to fit inside that limit. The
detailed retry policy (backoff shape, jitter, budget accounting) belongs to a
later task (M7-A2).

### J. Controlled stop

A controlled stop occurs only after N committed checkpoints of one named
kind, and is evaluated only after a successful transaction commit — never
mid-transaction and never speculatively before commit. Controlled stop
governs the process session, not the crawl run, and is explicitly excluded
from the crawl fingerprint. Detailed acceptance behavior belongs to a later
task (M7-A3c).

### K. Fingerprint

The system constructs the crawl fingerprint from the approved effective
configuration. Callers never supply an arbitrary fingerprint value directly.
The fingerprint excludes the raw source URL, credentials, the source ID, raw
query text, and any local filesystem path. Exact canonicalization rules
belong to a later task (M7-A3c).

### L. Owner-selected numeric profile (locked inputs for M7-A2)

The following values are the owner-locked numeric inputs for the future
`m7-crawl-reliability-v1` profile. They are recorded here once as the single
authoritative source for this document and are not implementation in M7-A1.

```text
profile_id: m7-crawl-reliability-v1
profile_version: "1"

inventory_page_size: 50
attachment_page_size: 50
minimum_request_interval_seconds: 3.0
max_response_bytes_per_request: 8388608
max_total_requests_per_run: 50000

max_attempts: 4
base_backoff_seconds: 1.0
max_retry_delay_seconds: 120.0
max_total_retry_delay_seconds: 300.0
jitter: false

max_include_roots: 16
max_pages_per_run: 10000
max_inventory_windows_per_root: 1000
max_inventory_windows_per_run: 4000
max_restriction_targets_per_page: 256
max_restriction_observations_per_run: 25000
max_attachment_windows_per_page: 100
max_attachment_windows_per_run: 10000

max_raw_bytes_per_run: 34359738368
max_raw_artifacts_per_run: 250000
minimum_free_disk_reserve_bytes: 8589934592
```

These values are materialized by M7-A2 in
`contracts/foundation/crawl_reliability_profile.yaml`. The profile remains a
contract artifact and authorizes no runtime behavior. Values may change only
through a new `profile_version` and, because the fingerprint is derived from
effective configuration (§2.K), a new crawl fingerprint.

## 3. Deferred implementation choices

The following are explicitly named but not resolved by M7-A1. Each is owned
by a later task as indicated:

- SQLite DDL, table/column shapes, and transaction boundaries beyond "one
  transaction covers a full window's rows and cursor state" — owned by a
  future M7-A3 persistence task.
- Overlapping-include-root deduplication mechanics beyond the ordered
  `(ancestor_page_id, ancestor_title)` compatibility rule — owned by M7-A3a.
- The exact restriction-evidence envelope serialization — owned by M7-A3b.
- Controlled-stop acceptance behavior and fingerprint canonicalization —
  owned by M7-A3c.
- Retry/backoff/budget semantics and the
  `m7-crawl-reliability-v1` profile file — owned by contract-only M7-A2.
  Structured HTTP metadata, pure retry-policy implementation, and the
  rate-limited executor remain future M7-B1/B2/B3 production tasks.
- File-lock library selection, raw-envelope JSON serialization, CLI flags,
  and production package/class names — owned by later reviewed
  implementation tasks, not by any contract-only task.

## 4. Unresolved operational items

- The exact SQLite file location, checkpoint database migration strategy,
  and operational backup/retention policy remain open and are not addressed
  by this document.
- The exact process for detecting and operator-resolving a same-fingerprint
  incomplete-run conflict (§2.F) beyond "fail closed" remains open.
- The interaction between controlled stop (§2.J) and an operator-initiated
  resume across process sessions remains open pending M7-A3c.
- Disk-space and quota enforcement behavior when approaching
  `minimum_free_disk_reserve_bytes` (§2.L) remains open pending M7-A3 and
  later production implementation.

## 5. Provenance and scope note

This document was authored directly in the current repository as a
contract-only task. It does not assume, require, or record a shared Git
commit SHA with any other repository. Any local commit mapping belongs only
in the repository's existing ignored local provenance file, never in this
document. No internal URL, hostname, username, token, local filesystem path,
source ID, real page ID, principal, real content, full runtime hash, or
machine identity appears in this document.
