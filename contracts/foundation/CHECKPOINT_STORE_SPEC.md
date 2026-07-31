# Confluence Checkpoint Store Specification (M7-C)

## 1. Status, authority, and scope

This is the focused M7-C contract for durable inventory state. It complements
the semantic run, resume, occurrence, and transaction rules in
`CHECKPOINT_RESUME_SPEC.md`; those rules remain authoritative for their stated
scope.

This contract defines no production implementation, database DDL, checkpoint
migration, live execution, raw-generation behavior, CLI, or backup/retention
policy. M7-C implementation remains separately gated and unauthorized.

## 2. Workspace and single-writer boundary

The caller supplies one validated workspace directory. M7-C derives only these
direct child paths:

```text
crawl_state.sqlite3
crawl_writer.lock
```

The directory chain and derived direct entries must not be symlinks or Windows
reparse points. The database, lock, and SQLite journal sidecars stay below that
one directory; callers cannot provide separate database and lock paths.

The process-lifetime exclusive OS lock is acquired before the database is
opened, initialized, or mutated. The database is closed before the lock is
released. No public API may expose a mutable connection or a state store outside
this locked workspace boundary.

M7-C uses `portalocker==3.2.0` (BSD-3-Clause) as its OS-handle lock dependency.
The supported M7-C operating-system matrix is Windows, Linux, and macOS; each
requires real child-process contention acceptance. The dependency is used only
for the exclusive process-lifetime lock and must not use PID ownership, lease
expiry, heartbeat, stale takeover, or delete-and-retry behavior.

## 3. Connection and schema profile

Every M7-C connection uses Python standard-library `sqlite3` with explicit
transaction control and verifies these settings before use:

```text
foreign_keys = ON
busy_timeout = 0
journal_mode = DELETE
synchronous = EXTRA
mutation begin = BEGIN IMMEDIATE
```

An unavailable or ineffective setting is `state_failure/checkpoint_failure`; the
implementation never silently downgrades durability or waits for another
writer. No database transaction spans network I/O.

An empty/new workspace initializes schema version 1. Only exact version 1 is
opened. Older, newer, absent, partial, malformed, or otherwise unknown schema
state fails closed. M7-C performs no automatic migration, repair, backup, or
retention operation.

The root occurrence is a distinct state entity from a descendants window. A
root is never represented by sentinel `window_start` or `item_ordinal` values.
Concrete DDL, table names, and column names remain a later focused
implementation decision.

## 4. Durable request-budget reservation

The durable request budget is the authority across process sessions. Its
conceptual state operation is:

```text
reserve_outbound_attempt(run_id)
  -> reserve exactly one remaining request-budget unit, or deny
```

The operation uses a short `BEGIN IMMEDIATE` transaction, commits before I/O,
and never refunds a committed reservation. It occurs immediately before every
outbound HTTP attempt, including retries. A crash after reservation and before
the transport starts may therefore consume a unit conservatively.

The retry executor may use a non-mutating durable-capacity check before a retry
sleep, then invokes the reservation seam immediately before B1 starts I/O. It
does not read SQLite, mutate checkpoint rows, or treat an in-memory counter as
the cross-session authority.

## 5. Durable inventory budget and completion

`max_pages_per_run` counts unique observed `page_id` values persisted in a run,
including root occurrences and pages later excluded from final projection. A
root or full descendants-window transaction computes its projected unique-ID
total before any mutation; an operation that would exceed the limit fails as
`budget_exhausted/inventory_page_budget_exhausted` with no partial rows, cursor
movement, root state, or transition.

Cross-root occurrences of an already observed page ID do not consume another
unique-page unit. Per-root occurrence facts remain durable for overlap
compatibility.

The M7 effective-input validator rejects more than `max_include_roots` before
fingerprinting, request, or durable mutation with
`budget_exhausted/include_root_limit_exhausted`. Before starting a descendants
request, durable counters check both `max_inventory_windows_per_root` and
`max_inventory_windows_per_run`. Reaching either cap yields
`budget_exhausted/inventory_window_limit_exhausted`; no next request or retry
sleep starts. These checks do not replace the atomic window/root budget checks.

After every root reaches `descendants_complete`, the durable inventory phase is
complete while the crawl run remains incomplete. A valid resume then returns
`inventory_complete` without a network request, checkpoint mutation, or
whole-run completion transition.

## 6. M7-C acceptance obligations

The offline M7-C store/inventory slice must prove at least:

- locked workspace rejects symlink/reparse redirection and second-process
  contention;
- every connection verifies the selected durability PRAGMAs;
- schema version failure is fail-closed without mutation;
- durable attempt reservation is never refunded across a crash or new session;
- a denied request budget starts no request and schedules no retry sleep;
- a crash after reservation before I/O cannot bypass the total request budget;
- page-budget overflow, cross-root duplicates, excluded pages, and transaction
  crash points preserve the committed-state invariants;
- root, include-root, per-root-window, and per-run-window limits stop at their
  exact cap and fail closed at cap plus one;
- inventory-complete resume is an idempotent no-op.

This is an inventory-only M7-C contract. It cannot close raw-generation,
full-M7 scale, live, or final M7 acceptance gates.
