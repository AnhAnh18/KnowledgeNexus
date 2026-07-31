# Confluence Checkpoint and Resume Specification (M7-A3a)

## 1. Status, authority, and scope

Status: contract-only M7-A3a contract complete and owner-approved.

```text
M7-A1: OWNER-APPROVED
M7-A1 independent review: WAIVED BY OWNER
M7-A2: COMPLETE AND APPROVED
M7-A3a: COMPLETE AND APPROVED
M7-A3b/A3c contract candidates: NOT YET RECORDED BY THIS DOCUMENT
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```

This specification narrows `CRAWL_RELIABILITY_SPEC.md` owner decisions B, E,
F, and G. It is authoritative for conceptual checkpoint atomicity, run
discovery, inventory occurrence identity, resume behavior, and overlapping
include-root compatibility.

It defines no SQLite DDL, table or column name, migration, Python interface,
filesystem path, production code, or live execution.

## 2. Run and process-session ownership

A crawl run owns:

```text
run_id
crawl fingerprint
raw generation identity
normalized inventory occurrences
durable checkpoint transitions
run completion state
```

A process session owns:

```text
writer-lock handle
session start/end
controlled-stop setting
process-local resources
```

One crawl run MAY span multiple process sessions. Starting a new process
session MUST NOT create a new crawl run when a resume operation was selected.
Session identity and controls MUST NOT alter run identity.

For M7-C version 1, a start-new operation receives a system-generated lowercase
canonical UUIDv4 `run_id`, and `generation_id` equals that `run_id`. A caller
may supply a validated existing `run_id` only as the selector for an explicit
resume; it cannot create or replace a run/generation identity. After every root reaches
`descendants_complete`, inventory is complete but the crawl run remains
incomplete. A valid resume of that inventory-complete run returns the idempotent
`inventory_complete` outcome without a network request, checkpoint mutation,
or whole-run completion transition.

## 3. Mutually exclusive run operations

Exactly one of these operations MUST be selected:

1. `start_new_run`
2. `resume_explicit_run_id`
3. `resume_unique_incomplete_run`

No operation may fall back to another:

- failed resume MUST NOT become start-new;
- zero unique-incomplete matches MUST fail closed;
- multiple unique-incomplete matches MUST fail closed;
- the newest matching run MUST NOT be selected automatically;
- start-new MUST fail when an incomplete same-fingerprint run exists;
- explicit abandonment is a separate future operator action and MUST NOT be
  inferred from start-new.

An explicit run ID is a caller-selected identity, not a caller-supplied
fingerprint. Fingerprints remain trusted-builder output under M7-A3c.

## 4. Inventory occurrence identity

An inventory occurrence is conceptually identified by:

```text
run_id
include_root_ordinal
include_root_page_id
window_start
item_ordinal
page_id
```

`include_root_ordinal` is assigned after canonical sorting of validated
include-root page IDs. It MUST NOT depend on operator input order. Duplicate
include-root IDs are rejected before any request or checkpoint mutation.

`window_start` is the numeric start requested for the committed response
window. `item_ordinal` is the zero-based position of the item in that
validated window. Replaying a committed identity with equivalent normalized
metadata is idempotent. Replaying it with conflicting metadata is a
`state_conflict`.

## 5. Window transaction invariant

One inventory window follows this conceptual order:

```text
fetch response
→ parse JSON
→ validate pagination
→ normalize every item
→ prepare one complete durable mutation
→ BEGIN TRANSACTION
   → write every normalized inventory occurrence
   → write or confirm window identity
   → write the observed per-window totalSize
   → advance next_start or mark the include root terminal
   → record exactly one committed checkpoint transition
→ COMMIT
```

The future persistence implementation MUST NOT:

- advance a cursor outside the transaction;
- expose only some rows from a window;
- commit only part of a window;
- mark a root terminal before all terminal-window rows are durable;
- increment a committed-transition counter before commit;
- acknowledge completion before the commit succeeds.

All writes in the conceptual transaction become visible together or none
becomes visible.

When the committed terminal window completes the final non-complete root, that
same transaction also records `inventory_phase=complete`. The final root rows,
root/cursor state, checkpoint transition, and inventory-phase completion are
never split across transactions.

### M7-C durable budget binding

For M7-C version 1, `max_pages_per_run` counts unique observed `page_id` values
durably persisted in a crawl run, including occurrences later excluded from the
final scope projection. Before mutating a descendants-window transaction, the
store checks whether the complete window would exceed that unique-ID limit and
fails the whole transaction when it would.

Before every outbound HTTP attempt, including a retry, the current process
session durably reserves one unit of `max_total_requests_per_run` immediately
before I/O. A reservation is never refunded after a crash, even if the process
cannot determine whether the remote server observed the attempt. The retry
executor uses this through a reviewed application-facing seam; it does not own
or access checkpoint storage.

## 6. Checkpoint monotonicity

Within one run and include root:

- committed window starts never move backward;
- `next_start` advances only from the current committed window;
- terminal state never becomes non-terminal;
- one committed logical window produces exactly one checkpoint transition;
- rolled-back work produces no transition;
- replay after an unknown acknowledgement outcome reads durable state before
  deciding whether work is already committed.

Conflicting replay, non-advancing cursors, and impossible state transitions
fail closed. They are never repaired using last-write-wins.

## 7. Crash matrix

| Crash point | Durable result | Required resume |
| --- | --- | --- |
| Before fetch | No change | Fetch current window |
| After fetch, before parse | No checkpoint change | Fetch again or use valid M7 raw evidence under A3b |
| After parse/normalize, before transaction | No rows or cursor change | Process the same window again |
| During transaction | Full rollback | Resume from the same committed cursor |
| After rows are staged but before cursor mutation | Full rollback | Resume from the same committed cursor |
| After commit, before caller acknowledgement | Rows and cursor both durable | Read state and begin the next window |
| After terminal commit | Root is durably complete | Do not fetch that root again |

An implementation MUST prove these outcomes through transaction/fault
injection tests before production authorization.

## 8. Pagination compatibility

Approved M5B semantics are preserved:

```text
next_start = response.start + response.size
terminal = next_start >= response.totalSize
```

For every window:

- `response.start` equals requested start;
- `response.size` equals the results count;
- result count does not exceed requested limit;
- `totalSize` is evaluated only for the current window;
- drift in `totalSize` is allowed and durably recorded as observation;
- no total is frozen across windows or sessions;
- `_links.next` is not authority and is not persisted as the resume cursor;
- a zero-size window is valid only when terminal;
- a non-terminal zero-size or non-advancing response fails closed.

M7 guarantees crash consistency, not an upstream point-in-time snapshot.

## 9. Overlapping include roots

Overlapping roots remain supported. Occurrences are retained per include root
until compatibility and deduplication are evaluated.

An ancestor path is represented as ordered pairs:

```text
[
  (ancestor_page_id, ancestor_title),
  ...
]
```

Two occurrences of the same `page_id` are compatible only when:

1. one complete pair path is an exact suffix of the other;
2. both ID and title match for every pair in the suffix;
3. every non-path metadata field agrees under the current mapper/domain
   contract.

Non-path metadata includes at least:

```text
page_id
title
space_key
parent_page_id
updated_at
source_version
labels
attachment_count
```

The compatible occurrence with the longest pair path becomes canonical.
That longest path is required for deny-safe scope/exclusion evaluation.

Conflicts include:

- equal ancestor IDs with different ancestor titles;
- neither path being a suffix of the other;
- two longest paths of equal length that differ;
- any non-path metadata disagreement.

Conflicts fail closed. There is no last-write-wins rule.

## 10. Scope and exclusion authority

Scope policy runs against the longest compatible canonical path after
cross-root compatibility succeeds. Therefore an excluded ancestor visible
only from an outer include root remains effective.

The deduplicated final normalized inventory contains at most one entry per
page ID. Excluded pages remain present as auditable inventory entries with
their approved scope status; deduplication MUST NOT silently discard them.

## 11. Stable ordering

Durable occurrence replay order is:

```text
include_root_ordinal
→ window_start
→ item_ordinal
```

Final deduplicated page output uses the approved deterministic inventory
ordering after canonical occurrence selection. Operator include-root order,
process-session boundaries, crash points, and replay MUST NOT alter the final
output.

## 12. Root and descendant state

Each include root conceptually advances through:

```text
root_pending
root_committed
descendants_pending
descendants_complete
```

The root occurrence is durable before descendants advance. A committed root
is not fetched again on resume. A root becomes descendants-complete only when
its terminal descendants window commits.

This specification defines states semantically, not as database enum values or
DDL.

## 13. Authoritative mutable-state boundary

The future mutable checkpoint database is the authority for run discovery,
inventory rows, cursors, transitions, and completion state.

`sync_state.jsonl` remains an exported diagnostic/snapshot record:

- it is not mutable checkpoint authority;
- it is not read to resume a crawl;
- it does not replace transactional state;
- M7-A3a does not modify its schema.

Checkpoint databases, runtime rows, run IDs, raw fingerprints, and operational
paths remain outside Git history.

## 14. Failure disposition

At minimum these conditions fail closed without retrying an HTTP request:

```text
run_operation_invalid
run_not_found
run_not_resumable
run_match_ambiguous
incomplete_run_conflict
inventory_identity_conflict
inventory_metadata_conflict
pagination_invalid
checkpoint_failure
state_conflict
request_budget_exhausted
inventory_page_budget_exhausted
```

Names are contract-facing stable categories for future implementation review.
They MUST NOT include raw database, path, exception, page, or fingerprint
values in `str`, `repr`, logs, or durable evidence.

## 15. Deterministic acceptance matrix

| ID | Required case and result |
| --- | --- |
| `A3A-RUN-01` | Explicit valid run resumes exactly that run |
| `A3A-RUN-02` | Unique incomplete lookup resumes its single match |
| `A3A-RUN-03` | Zero incomplete matches fail closed |
| `A3A-RUN-04` | Multiple incomplete matches fail closed |
| `A3A-RUN-05` | Start-new with same-fingerprint incomplete run fails |
| `A3A-RUN-06` | Operation selection count other than one fails before mutation |
| `A3A-RUN-07` | Inventory-complete resume is an idempotent no-op with no HTTP request |
| `A3A-TXN-01` | Crash before transaction leaves rows/cursor unchanged |
| `A3A-TXN-02` | Crash during row insertion rolls back all rows |
| `A3A-TXN-03` | Crash after row staging but before cursor mutation rolls back |
| `A3A-TXN-04` | Crash after commit before acknowledgement resumes next window |
| `A3A-TXN-05` | Terminal-window commit persists rows and root completion together |
| `A3A-TXN-06` | Rolled-back transaction does not increment transition count |
| `A3A-TXN-07` | The final terminal window commits inventory completion atomically |
| `A3A-PAGE-01` | Per-window totalSize drift remains accepted and recorded |
| `A3A-PAGE-02` | Non-terminal zero-size window fails closed |
| `A3A-PAGE-03` | Non-advancing cursor fails closed |
| `A3A-BUDGET-01` | Excluded pages count once; cross-root duplicates do not consume a second unique-page unit |
| `A3A-BUDGET-02` | A window exceeding the unique-page budget commits no partial rows, cursor, or transition |
| `A3A-ROOT-01` | Two nested roots deduplicate compatibly |
| `A3A-ROOT-02` | Three nested roots select the longest compatible path |
| `A3A-ROOT-03` | Reversed input-root order produces identical state/output |
| `A3A-ROOT-04` | ID/title suffix-compatible paths are accepted |
| `A3A-ROOT-05` | Same suffix IDs with different title fails closed |
| `A3A-ROOT-06` | Non-path metadata disagreement fails closed |
| `A3A-ROOT-07` | Excluded ancestor visible only in longest path still excludes |

Future fault-injection tests MUST compare resumed state and final normalized
inventory with an uninterrupted run.

## 16. Review gate

An independent reviewer must confirm:

- transaction semantics prove no cursor-without-rows state;
- run operations never fall back or choose the newest run;
- ambiguous run discovery fails closed;
- per-window `totalSize` compatibility remains unchanged;
- overlapping roots avoid false conflicts while preserving exclusions;
- ordering is independent of input order and process sessions;
- no DDL, persistence implementation, source/test/schema change, network
  request, or production authorization exists.

Until integrated review accepts A1/A2/A3:

```text
M7-CONTRACT-GATE: APPROVED
M7 production implementation: NOT AUTHORIZED
```
