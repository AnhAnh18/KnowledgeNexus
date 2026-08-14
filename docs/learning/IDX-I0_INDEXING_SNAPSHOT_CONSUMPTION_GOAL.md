# IDX-I0 Indexing Snapshot Consumption Goal

## Purpose and boundary

This backlog is the execution record for the approved Foundation-to-Indexing
snapshot-consumption stack. It lists work in the required order only; listing a
future item does not authorize it. `IDX-I0` is documentation-only. No item in
this document authorizes a Foundation direct chunk write or a production change
before its stated dependencies, owner decisions, and independent review gate.

Naming follows `docs/ROADMAP_WRITING_RULES.md`. `IDX-D9`, `IDX-D10`,
`IDX-D11`, `IDX-D12`, and `IDX-D13` are qualified references to the handoff
plan's owner decisions D9-D13 rather than inferred implementation approvals.
`IDX-C1`, `IDX-B1`, and `IDX-RET-GC` are qualified backlog IDs for the named
plan stages. Phase A resolves the commit-tag convention as `IDX-*`.

## Status and order

| Order | ID | Level | Owner | Status | Blocking condition |
|---:|---|---|---|---|---|
| 1 | IDX-I0 | discovery/report | Indexing | review | None; may require rebase after `M10-W5 (historically W5-D closeout)`. |
| 2 | IDX-D12 | owner decision | Foundation/shared-contract owners | done | Phase A disposition and digest-set specification recorded. |
| 3 | IDX-C1 | contract implementation | Foundation/shared-contract owners | blocked | IDX-D12 and `M10-W5 (historically W5-D closeout)`. |
| 4 | IDX-B1 | immutable delivery bridge | Foundation/delivery | blocked | IDX-C1, IDX-D10, IDX-D11, IDX-D9, `M10-W5 (historically W5-D closeout)`. |
| 5 | IDX-I1 | resolver + validate-before-write | Indexing | blocked | Implementation: separate owner GO after IDX-D12/A7; acceptance: IDX-C1, IDX-B1, IDX-D10, `M10-W5 (historically W5-D closeout)`. |
| 6 | IDX-I2-A | identity/provenance/staging migration | Indexing | blocked | IDX-I1, IDX-D4, IDX-D5, IDX-D6, IDX-D7, IDX-D8, IDX-D13, `M10-W5 (historically W5-D closeout)`. |
| 7 | IDX-I2-B | full-snapshot staged importer | Indexing | blocked | IDX-I2-A, IDX-D7, `M10-W5 (historically W5-D closeout)`. |
| 8 | IDX-I3 | two-store verification + activation | Indexing | blocked | IDX-I2-B, IDX-D8, IDX-D13, `M10-W5 (historically W5-D closeout)`. |
| 9 | IDX-RET-GC | retention and garbage collection | Foundation/Indexing operations | blocked | IDX-D13 retention policy, IDX-I3, `M10-W5 (historically W5-D closeout)`. |
| 10 | IDX-I2-C | delta/base-chain/tombstone import | Indexing | blocked | IDX-D13, IDX-RET-GC, active-base acknowledgement, divergence detection, full fallback. |
| 11 | IDX-I4-A | Foundation outbox producer | Foundation | blocked | IDX-I3, IDX-D9, IDX-D10, IDX-D11, `M10-W5 (historically W5-D closeout)`. |
| 12 | IDX-I4-B | Indexing consumer | Indexing | blocked | IDX-I4-A, IDX-I3, IDX-D9, IDX-D10, IDX-D11, `M10-W5 (historically W5-D closeout)`. |
| 13 | IDX-I5 | end-to-end acceptance + closeout | Foundation/Indexing | blocked | IDX-I4-B, `M10-W5 (historically W5-D closeout)`. |

`M10-W5 (historically W5-D closeout)` denotes the documentation/review closeout
and official post-W5 freeze named in the Foundation roadmap. W5-B is in
progress; W5-C and the W5-D closeout are not complete, so this backlog must be
rebased against that frozen head before code work starts.

## Work-item records

### IDX-I0

- Owner: Indexing team. Status: review.
- Objective: Produce a verified compatibility report and this ordered backlog.
- Scope: Read-only reconciliation of contracts, current Foundation producer,
  current Indexing base, and RET-R2 constraints.
- Out of scope: Production code, D12/B1/I1 work, live capture, direct chunk
  writes, and edits to the handoff plan or roadmap.
- depends_on: `M10-W5 (historically W5-D closeout)` is not a start prerequisite,
  but its future freeze is
  a mandatory rebase prerequisite for every code item after this one.
- Acceptance: Report identifies every required matrix area with code evidence;
  it rejects the legacy ten-file, destination-`LATEST.txt`, and optional
  `sync_state.jsonl` assumptions; negative evidence records fail-closed gaps.
- Evidence: `docs/learning/IDX-I0_COMPATIBILITY_REPORT.md` and
  a fresh independent review `REV-IDX-01` before I1 scope freeze.

## Owner Decision IDX-D12

- Owner: Foundation/shared-contract owners. Status: done for the Phase A
  inventory disposition.
- Objective: Record the D12 member-inventory rule and pre-D12 snapshot policy.
- Scope: Digest-set source-of-truth membership, schema-version-keyed allowed
  names, and mandatory offline re-export for pre-contract snapshots.
- Out of scope: Producer/shared-contract implementation, importer, Qdrant,
  delivery automation, and delta recovery.
- depends_on: Owner disposition.
- Acceptance: The recorded decision identifies the inventory rule and re-export
  policy; it does not invent a `manifest.dataset_name` field.
- Evidence: `docs/learning/IDX-I0_PHASE_A_OWNER_DECISIONS.md` and
  `docs/learning/IDX-D12_DIGEST_SET_SPECIFICATION.md`.

### IDX-C1

- Owner: Foundation/shared-contract owners. Status: blocked by `IDX-D12` and
  `M10-W5 (historically W5-D closeout)`.
- Objective: Version the snapshot integrity and dataset-identity contract and
  implement the approved producer/shared-contract changes.
- Scope: Add the digest-set eleventh member; bind manifest/digest-set trigger
  digests; update Foundation exact-file gates.
- Out of scope: Importer, Qdrant, delivery automation, and delta recovery.
- depends_on: `M10-W5 (historically W5-D closeout)`, owner decision `IDX-D12`.
- Acceptance: The current schema-version member table has eleven delivered
  members; all members verify before parsing; a missing,
  extra, substituted, truncated, or digest-mismatched member fails closed;
  old snapshots follow the `IDX-D12` owner-approved re-export policy.
- Evidence: Versioned schema/contract diff, producer tests, negative integrity
  tests, and independent review `REV-IDX-02`.

`IDX-D12` records the Phase A inventory/re-export disposition. It does not
select an unapproved `manifest.dataset_name` form; that contract boundary must
be resolved before IDX-C1 implementation is authorized.

### IDX-B1

- Owner: Foundation/delivery team. Status: blocked by `IDX-C1`, `IDX-D9`,
  `IDX-D10`, `IDX-D11`, and `M10-W5 (historically W5-D closeout)`.
- Objective: Deliver one immutable full snapshot to an Indexing-visible
  destination without exposing partial data.
- Scope: `.incoming` isolation, delivery ledger, no-clobber single writer,
  destination verification, atomic exposure, exact version/digest trigger,
  D9 projection through `delivery_available`.
- Out of scope: Destination `LATEST.txt`, Indexing import, Qdrant, outbox.
- depends_on: `IDX-C1`, `M10-W5 (historically W5-D closeout)`, owner decisions `IDX-D9`, `IDX-D10`,
  `IDX-D11`.
- Acceptance: Tamper, path/reparse escape, partial copy/crash, quota failure,
  duplicate trigger, and host outage do not expose a partial version; replay
  is idempotent and retains only aggregate sanitized evidence.
- Evidence: Bridge ledger tests, fault-injection tests, aggregate transfer
  report, and independent review `REV-IDX-03`.

### IDX-I1

- Owner: Indexing team. Status: blocked.
- Implementation gate: separate owner GO after Phase A4/A7; it has no
  dependency on `IDX-C1` implementation or `IDX-B1` delivery.
- Acceptance gate: `IDX-C1`, `IDX-B1`, `IDX-D10`, and
  `M10-W5 (historically W5-D closeout)`.
- Objective: Resolve one exact immutable snapshot and validate it entirely
  before any storage mutation.
- Scope: Explicit dataset/version/digests, D12 inventory verification, strict
  bounded parsing, shared-schema validation, cross-stream closure, and an
  ownership-isolated verified reader.
- Out of scope: Storage mutation, embedding, Qdrant, delta application, and
  destination/event-triggered `LATEST.txt`.
- implementation_depends_on: Phase A4/A7 as recorded in
  `docs/learning/IDX-I0_PHASE_A_OWNER_DECISIONS.md` and
  `docs/learning/IDX-D12_DIGEST_SET_SPECIFICATION.md`; no dependency on
  `IDX-C1` implementation or `IDX-B1` delivery.
- acceptance_depends_on: `IDX-C1`, `IDX-B1`,
  `M10-W5 (historically W5-D closeout)`, and owner decision `IDX-D10`.
- Acceptance: Wrong runtime types, `None`, duplicate JSON keys, NaN/infinity,
  blank lines, forbidden files, missing members, bad counts, reparse objects,
  path traversal, digest mismatch, and TOCTOU replacement fail before a write.
- Evidence: Resolver/validator tests, bounded-resource tests, dependency-boundary
  tests, and independent review `REV-IDX-04`.

### IDX-I2-A

- Owner: Indexing team. Status: blocked by `IDX-I1`, owner decisions, and
  `M10-W5 (historically W5-D closeout)`.
- Objective: Create versioned identity/provenance and staged-storage
  foundations required for safe activation.
- Scope: Foundation string IDs, UUIDv5 Qdrant mapping, entity repositories,
  dataset/version fields, payload indexes, versioned collections/aliases, and
  durable activation ledger.
- Out of scope: Full import orchestration, delta mutation, event consumer.
- depends_on: `IDX-I1`, `M10-W5 (historically W5-D closeout)`, owner decisions `IDX-D4`, `IDX-D5`,
  `IDX-D6`, `IDX-D7`, `IDX-D8`, `IDX-D13`.
- Acceptance: Non-UUID Foundation IDs map deterministically; missing ACL or
  provenance/index fields fail closed; impossible ledger status/count fields,
  duplicate/conflicting identities, and migration rollback failures are tested.
- Evidence: Migration tests, Qdrant schema/index tests, ledger tests, and
  independent review `REV-IDX-05`.

### IDX-I2-B

- Owner: Indexing team. Status: blocked by `IDX-I2-A`, `IDX-D7`, and
  `M10-W5 (historically W5-D closeout)`.
- Objective: Stage an idempotent full-snapshot import through injected ports.
- Scope: Durable job identity, Foundation record mapping, verbatim document
  embedding, staged hydrate/Qdrant writes, and ready-for-activation state.
- Out of scope: Delta/base-chain processing, reader-visible activation, direct
  `/v1/store/chunks` handoff, and SnapshotReady consumer.
- depends_on: `IDX-I2-A`, `M10-W5 (historically W5-D closeout)`, owner decision `IDX-D7`.
- Acceptance: Same successful identity makes no duplicate rows/points or
  unintended re-embedding; conflicting digest/version, wrong records/vector
  count/dimension/non-finite vector, and backend failure leave no active data.
- Evidence: Import/job idempotency tests, mock-port failure tests, aggregate
  staged-count report, and independent review `REV-IDX-06`.

### IDX-I3

- Owner: Indexing team. Status: blocked by `IDX-I2-B`, `IDX-D8`, `IDX-D13`, and
  `M10-W5 (historically W5-D closeout)`.
- Objective: Verify both staged stores and atomically make only a verified
  version reader-visible.
- Scope: Count/identity/provenance/index verification, activation-ledger switch,
  restart reconciliation, and sanitized terminal status.
- Out of scope: Delta import, source delivery, event production/consumption.
- depends_on: `IDX-I2-B`, `M10-W5 (historically W5-D closeout)`, owner decisions `IDX-D8`, `IDX-D13`.
- Acceptance: Hydrate-only or Qdrant-only success, malformed verification
  result, stale version, failed restart reconciliation, and impossible counters
  retain the prior ledger-selected active version.
- Evidence: Two-store fault tests, crash/restart tests, activation-ledger
  evidence, and independent review `REV-IDX-07`.

### IDX-RET-GC

- Owner: Foundation/Indexing operations. Status: blocked by `IDX-I3`, `IDX-D13`,
  and `M10-W5 (historically W5-D closeout)`.
- Objective: Retain bases, staged artifacts, rollback versions, and pending
  deliveries safely enough to support recovery and future deltas.
- Scope: Owner-approved retention/capacity/quota policy, cleanup ownership,
  recovery, and tests for snapshot, stage, and rollback artifacts.
- Out of scope: Delta application and broad storage optimization.
- depends_on: `IDX-I3`, `M10-W5 (historically W5-D closeout)`, owner decision `IDX-D13`.
- Acceptance: Cleanup never removes the active version, required base, pending
  delivery, or rollback target; quota/retention conflicts and unknown ownership
  fail closed and are recoverable.
- Evidence: Retention policy, cleanup/recovery tests, capacity evidence, and
  independent review `REV-IDX-08`.

### IDX-I2-C

- Owner: Indexing team. Status: blocked by `IDX-I3`, `IDX-RET-GC`, `IDX-D13`,
  and `M10-W5 (historically W5-D closeout)`.
- Objective: Apply accepted delta snapshots with base-chain and entity-specific
  tombstone semantics.
- Scope: Base acknowledgement, divergence detection, tombstone-before-upsert,
  ACL-only updates, and full-snapshot fallback invocation.
- Out of scope: In-place shared-collection UUIDv5 delta updates and unapproved
  transactional recovery designs.
- depends_on: `IDX-I3`, `IDX-RET-GC`, `M10-W5 (historically W5-D closeout)`, owner decision `IDX-D13`.
- Acceptance: Missing/wrong/stale base, divergent chain, unknown entity type,
  invalid tombstone, mismatched ACL update, and failed fallback leave the active
  version unchanged and do not expose removed records.
- Evidence: Delta-chain/tombstone/recovery tests, aggregate reconciliation
  report, and independent review `REV-IDX-09`.

### IDX-I4-A

- Owner: Foundation team. Status: blocked by `IDX-I3`, `IDX-D9`, `IDX-D10`,
  `IDX-D11`, and `M10-W5 (historically W5-D closeout)`.
- Objective: Persist and deliver `SnapshotReady` notifications after valid
  publication.
- Scope: Versioned event contract, no-clobber Foundation outbox, at-least-once
  delivery, reconciliation, D9 status projection, and sanitized metadata.
- Out of scope: Indexing event consumption and import implementation.
- depends_on: `IDX-I3`, `M10-W5 (historically W5-D closeout)`, owner decisions `IDX-D9`, `IDX-D10`,
  `IDX-D11`.
- Acceptance: Publication/event gap, duplicate event, unavailable receiver,
  malformed event, and retry exhaustion preserve the source snapshot and never
  emit content, paths, credentials, or full hashes.
- Evidence: Outbox/reconciliation tests, sanitized status tests, and
  independent review `REV-IDX-10`.

### IDX-I4-B

- Owner: Indexing team. Status: blocked by `IDX-I4-A`, `IDX-I3`, `IDX-D9`,
  `IDX-D10`, `IDX-D11`, and `M10-W5 (historically W5-D closeout)`.
- Objective: Consume exact `SnapshotReady` events idempotently and acknowledge
  only approved terminal import outcomes.
- Scope: Event validation/deduplication, exact resolver invocation, terminal
  acknowledgement persistence, and D9 read-only projection extension.
- Out of scope: Source publication, destination `LATEST.txt`, and inference of
  success from receipt or missing acknowledgement.
- depends_on: `IDX-I4-A`, `IDX-I3`, `M10-W5 (historically W5-D closeout)`, owner decisions `IDX-D9`,
  `IDX-D10`, `IDX-D11`.
- Acceptance: Missing/wrong fields, `object()`, `None`, wrong enums, duplicate
  and out-of-order events, conflicting version/digest, and premature ack fail
  closed before resolver/storage side effects.
- Evidence: Consumer boundary tests, acknowledgement/replay tests, and
  independent review `REV-IDX-11`.

### IDX-I5

- Owner: Foundation/Indexing teams. Status: blocked by `IDX-I4-B` and
  `M10-W5 (historically W5-D closeout)`; delta acceptance additionally requires `IDX-I2-C`.
- Objective: Prove the approved full and later delta handoff end to end and
  close the implementation stack.
- Scope: Deterministic fixtures/sanitized published snapshots, delivery,
  import, activation, acknowledgement, recovery, and closeout evidence.
- Out of scope: Live Confluence capture, raw evidence, and unapproved transport
  expansion.
- depends_on: `IDX-I4-B`, `M10-W5 (historically W5-D closeout)`; delta scenarios additionally depend_on:
  `IDX-I2-C`.
- Acceptance: The plan's happy paths succeed; malformed snapshot/event/digest,
  transfer/activation crashes, stale triggers, unavailable hosts, invalid ACL,
  and resource exhaustion produce zero unauthorized visibility or mutation.
- Evidence: Focused and affected regression commands, `compileall`, `git diff
  --check`, aggregate-only acceptance evidence, and independent review
  `REV-IDX-12`.

## Phase A owner dispositions

Phase A resolves the commit-tag convention as `IDX-*`; requires offline
re-export (not a compatibility flag) for pre-D12 snapshots; records the
digest-set inventory rule/specification; and reserves Indexing-base import for
IDX-I2-A after the frozen post-W5-D head. See
`docs/learning/IDX-I0_PHASE_A_OWNER_DECISIONS.md`.
