# M7-C Owner Decisions - Durable Inventory State

## Status and authority

```text
M7-C decision package: OWNER-APPROVED
M7-C production implementation: NOT AUTHORIZED
Full M7 acceptance: NOT AVAILABLE
M7-D raw-generation integration: BLOCKED
M7 scale RSS threshold: PENDING REPRODUCIBLE BASELINE
```

This record locks the owner choices needed to plan the durable-inventory M7-C
slice. It does not authorize production code, a live crawl, raw-generation
work, a checkpoint migration, or a full M7 acceptance claim. A focused plan
and a separate implementation authorization remain required for every M7-C
production stage.

Precedence: `contracts/foundation/schemas/` and the focused M7 specs remain
authoritative. The clarifications mirrored into `CHECKPOINT_RESUME_SPEC.md`,
`CHECKPOINT_STORE_SPEC.md`, `CRAWL_RELIABILITY_SPEC.md`,
`RETRY_POLICY_SPEC.md`, `RAW_GENERATION_SPEC.md`, and
`CRAWL_ACCEPTANCE_SPEC.md` govern any field-level or behavioral dispute. This
record supplies the approved owner choices and their rationale; it never permits
a lower-precedence document to override a focused spec.

## 1. Durability posture

M7-C prioritizes fail-closed crash durability and resume correctness over
throughput. A conservative durable count or a stopped run is acceptable; a
resume that bypasses a budget, mutates an unprotected database, or silently
uses incompatible state is not.

## 2. Approved decisions

### OD-C1. Trusted effective input and fingerprint registry

M7-C creates an M7-only effective-input validator before fingerprinting. It
must validate every profile bound used by the fingerprint and require the
effective inventory page size to equal the active reliability-profile value.
It does not change the existing M5 `ConfluenceSourceConfig` behavior.

The version-1 fingerprint registry values are:

```text
fingerprint_contract_version: m7-crawl-fingerprint-v1
deployment_api_family: confluence-data-center-rest-v1
request_profile_version: m7-confluence-request-profile-v1
scope_policy_version: m5-scope-policy-v1
query_shape_profile_version: m7-confluence-inventory-query-v1
expand_shape_profile_version: m7-confluence-inventory-expand-v1
mapper_contract_version: m5b-confluence-inventory-mapper-v1
raw_layout_contract_version: m7-raw-generation-layout-v1
foundation_schema_version: "1.0"
chunking_contract_version: 1.2.0
jira_relation_contract_version: m6e-jira-relations-v1
acl_contract_version: m6f-acl-materialization-v1
```

`scope_config_digest` hashes the canonical UTF-8 JSON object containing exactly
the include-root labels keyed by page ID, excluded-subtree reasons keyed by page
ID, and the include/exclude keyword collections. Page IDs themselves are
already represented directly in the fingerprint object. The keyed entries are
sorted by canonical page-ID order; keyword collections are duplicate-free and
sorted by canonical string order; absent labels/reasons use explicit `null`.
Only the digest is persisted or emitted. `source_id`, raw endpoint input,
credentials, raw query text, and local paths remain excluded.

### OD-C2. Run and generation identity

The system generates a lowercase canonical UUIDv4 `run_id` for start-new. In
M7-v1, `generation_id` equals `run_id`; a caller may supply a validated existing
`run_id` only to select an explicit resume, never to create/replace either
identity. One run therefore owns one generation without an unnecessary second
random identifier.

### OD-C3. SQLite durability profile

M7-C uses Python standard-library `sqlite3` with explicit transaction control:

```text
mutation begin mode: BEGIN IMMEDIATE
foreign_keys: ON
busy_timeout: 0
journal_mode: DELETE
synchronous: EXTRA
```

Every connection must verify the selected PRAGMAs before use. Unsupported or
ineffective settings fail as sanitized `checkpoint_failure`; they must never
downgrade silently. This serialized, fail-fast profile is chosen for durable
single-writer correctness, not write concurrency or peak throughput.

### OD-C4. Schema evolution

An empty/new workspace initializes schema version 1. Only exact version 1 opens
normally. Older, newer, missing, or malformed versions fail closed. M7-C has no
automatic migration, repair, backup, or retention behavior.

### OD-C5. Workspace layout and path safety

The caller supplies exactly one trusted workspace directory. Infrastructure
derives the only allowed mutable names below it:

```text
crawl_state.sqlite3
crawl_writer.lock
```

The database, lock, and SQLite sidecars must remain in that directory. The
directory chain and direct entries are verified not to be symlinks or Windows
reparse points before create/open. Callers cannot choose independent database
and lock paths.

### OD-C6. Root storage

Each root occurrence has storage and lifecycle distinct from a descendants
window. M7-C never encodes a root using a sentinel `window_start` value.
Canonical `include_root_ordinal` follows sorted, unique root page IDs.

### OD-C7. Writer lock mechanism

M7-C uses `portalocker==3.2.0` (BSD-3-Clause) as one version-pinned,
cross-platform OS-handle locking dependency. It supports Windows, Linux, and
macOS, each with child-process contention acceptance. It is used only for the
exclusive process-lifetime lock, never as a substitute for workspace path
validation. PID ownership, TTL, heartbeat, stale takeover, and delete-and-retry
behavior remain prohibited.

### OD-C8. Page budget meaning

`max_pages_per_run` counts unique observed `page_id` values durably persisted
in the run, including pages later excluded from final scope projection. A
root occurrence or complete descendants-window transaction checks its projected
unique-ID total before mutation; it fails closed as a budget outcome when the
complete transaction would exceed the limit. No partial root/window rows,
cursor, root state, or transition may commit on that outcome. A cross-root
occurrence of an already observed ID consumes no new unique-page unit. Per-root
occurrence rows remain independently bounded by the existing include-root and
window limits.

### OD-C9. Inventory completion and resume

After all roots reach `descendants_complete`, `inventory_phase` is complete but
the crawl run remains incomplete. M7-C does not own later raw, page,
restriction, or attachment phases. A valid resume of an inventory-complete run
returns an idempotent `inventory_complete` outcome without a network request,
checkpoint mutation, or whole-run completion transition.

### OD-C10. CLI scope

M7-C creates no production live-crawl CLI. A future CLI may expose separate
`start-new`, `resume-run <run_id>`, and `resume-unique` commands, but it cannot
accept a caller-supplied fingerprint. This direction is not a blocker for the
M7-C implementation slices.

### OD-C11. Durable outbound-attempt reservation

Before every outbound HTTP attempt, including retries, M7-C must durably reserve
one unit of the per-run request budget immediately before I/O. A process crash
after reservation may conservatively consume a request-budget unit even if no
outbound attempt reached the remote server; reservations are never refunded.
This prevents a crash or session change from bypassing
`max_total_requests_per_run`.

The retrying executor retains ownership of retry selection, pacing, and the
attempt loop. It receives a reviewed reservation seam and must not access
SQLite or checkpoint internals directly. The reservation handshake is required
before the M7-C offline coordinator stage.

### OD-C12. Scale-gate threshold procedure

The absolute child-process RSS growth threshold remains unchosen until a
reproducible baseline exists. It must be owner-locked before approval of the
M7 scale gate; no implementation or closeout may invent a threshold after
measuring a candidate. This is not a precondition for M7-C's early focused
stages and is intentionally not represented as an already-locked numeric value.

### OD-C13. Offline scale acceptance profile

The 100,000-page extended offline corpus uses the versioned,
acceptance-only `m7-crawl-scale-acceptance-v2` / `"2"` profile. Its distinct
numeric version is required because it raises `max_pages_per_run=100000` and
`max_inventory_windows_per_root=2000`; its distinct profile identity produces a
distinct crawl fingerprint. It is not a production or live-crawl profile.

This is an inventory-cap profile, not an alternate B2 retry-policy profile.
Both the functional and extended gates construct B2 policy only from the exact
approved `m7-crawl-reliability-v1` / `"1"` mapping. The scale profile preserves
that mapping's numeric/boolean retry parameters and MUST NOT be passed to the
B2 policy constructor.

### OD-C14. Root-relative parent context for occurrence compatibility

`parent_page_id` in an inventory occurrence is root-relative context, not a
stable cross-root metadata field. A selected include root may therefore have
an empty ancestor path and `parent_page_id=None`, while the same page observed
under an outer include root has a non-empty path and a contextual parent. Each
occurrence must still fail closed unless its parent is internally consistent
with its own path: null exactly for an empty path, otherwise the final ancestor
ID.

Cross-root compatibility compares the stable metadata fields and exact
suffix-compatible `(ancestor_page_id, ancestor_title)` paths, but does not
compare contextual parents across occurrences. The longest compatible path is
canonical and supplies the canonical parent. This preserves existing M5 and
M7-C1-A root-relative mapper behavior while allowing nested roots to
deduplicate without weakening fail-closed checks for malformed paths or stable
metadata conflicts.

### OD-C15. Operation-specific session API and deferred hardening

M7-C uses named, typed operations at the application/session boundary rather
than a caller-provided generic mutation callback. C2-B retains its private
registry until a reviewed state/session port is introduced. C2-C/C2-D must
introduce a method-oriented state API covering run selection
(`start_new_run`, `resume_explicit_run`, `resume_unique_incomplete_run`) and
the subsequently-defined operations `reserve_outbound_attempt`,
`load_next_inventory_work`, `commit_root_occurrence`,
`commit_inventory_window`, and `stream_inventory_occurrences`. No placeholder
method may be added before its command/result value objects and durable
semantics are implemented.

The existing trusted-input, workspace-path, lock-lifetime, SQLite durability,
and sanitized-failure requirements remain active contract invariants. Broader
API-security hardening is intentionally deferred until the final M7 readiness
review. That review must close this checklist before any production/live
authorization:

- audit session and return-object graphs for retained mutable connection,
  transaction, workspace, path, or lock references;
- restrict every public operation to typed commands and typed outcomes, with
  no generic execute/mutate/callback escape hatch;
- add adversarial lifecycle tests for stale sessions, exceptions, and retained
  objects after context exit;
- review workspace ownership/OS permissions and validate the supported
  Windows, Linux, and macOS boundary behavior; and
- complete a threat model covering caller-controlled configuration and durable
  checkpoint data, then add the resulting focused regression tests.

### OD-C16. Deferred 100,000-page performance optimization

The owner chooses to keep the current durability-first validation boundary and
does not authorize a performance/durability optimization stage for the
100,000-page offline scale gate at this time. The
`m7-crawl-scale-acceptance-v2` profile remains acceptance-only, and the scale
gate remains pending/incomplete.

Any future optimization must be proposed as a separate owner-authorized stage
and must re-review writer-lock/sidecar verification cadence, external-writer
threat-model assumptions, invalidation rules, schema or index changes, and any
RSS/working-set threshold. This decision changes no production behavior,
profile values, or acceptance result.

## 3. Required closure boundaries

An inventory-only M7-C acceptance suite may close only M7-C after independent
approval. It cannot claim full M7 completion because raw-generation evidence,
its acceptance cases, and the full M7 scale gate remain later work. M7-D
raw-generation integration stays blocked until its own focused plan is approved.

## 4. Durable recording and provenance

This committed record and its focused-spec clarifications are the durable source
for these decisions. `.codex-workflow/`, checkpoint databases, raw artifacts,
and local SHA mappings are not durable decision records. Commit SHAs remain
repository-local provenance only and do not authorize any implementation.
