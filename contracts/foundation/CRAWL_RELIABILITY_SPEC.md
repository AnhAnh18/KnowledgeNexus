# Crawl Reliability Specification (M7-A1)

Status: owner-approved M7-A1 focused contract for crawl reliability and scale.

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

Precedence: `contracts/foundation/schemas/` wins every field-level dispute.
This specification sits with the other active focused specifications
(`CHUNKING_SPEC.md`, `JIRA_RELATION_SPEC.md`, `ACL_MATERIALIZATION_SPEC.md`,
`ONE_PAGE_EXPORT_SPEC.md`, `RETRY_POLICY_SPEC.md`,
`CHECKPOINT_RESUME_SPEC.md`, `CHECKPOINT_STORE_SPEC.md`,
`RAW_GENERATION_SPEC.md`, and `CRAWL_ACCEPTANCE_SPEC.md` with the M7
reliability profiles) above the historical decision logs. It is a
contract for future crawl-reliability work; it authorizes no production
implementation. The owner decisions this specification narrows are recorded
in `decision_logs/M7_OWNER_DECISIONS.md`, which remains the authoritative
owner record of the locked numeric profile inputs, and the follow-on
`decision_logs/M7_C_OWNER_DECISIONS.md` for M7-C durability decisions.

## 1. Purpose and non-goals

Purpose: define the crawl-reliability contract that lets Foundation scale the
approved M6 one-page vertical slice to many pages and attachments without
changing approved M5/M6 record, scope, ACL, chunking, relation, or export
semantics.

Non-goals:

- M7-A1 does not implement retry, rate limiting, checkpoint persistence,
  SQLite, a raw-generation store, file locking, or crawl orchestration.
- M7-A1 does not perform, authorize, or describe any controlled live
  execution.
- M7-A1 does not reopen or reinterpret the approved M6G one-page export
  contract or its acceptance evidence.
- M7-A1 does not define SQLite tables/columns, Python interfaces, retry loop
  code, file-lock library selection, raw-envelope JSON serialization, full
  fingerprint canonicalization, CLI flags, or production package/class names.
  M7-A2 defines retry semantics only; M7-A3 owns the remaining contract
  mechanics, while retry loop code and other runtime components remain later
  production tasks.
- Production implementation of any M7 behavior remains blocked until the
  complete M7-A1/A2/A3 contract gate is accepted and production work receives
  explicit authorization.

## 2. Preserved M5/M6 semantics

M7 is additive reliability scaffolding around the already-approved crawl and
export path. Unless a section below states an explicit additive reliability
contract, M7 preserves:

- M5A scope policy (include roots, excluded subtrees, keyword hints as
  advisory only);
- M5B Data Center response mapping and numeric pagination correctness;
- M6A raw-page preservation at its deterministic fixed path;
- M6B restriction/attachment observation capture at its deterministic fixed
  paths;
- M6C normalization, M6D chunking, M6E Jira relation extraction, M6F ACL
  materialization, and M6G one-page export record and projection semantics.

M7 does not change any JSON Schema, any chunk/document/relation/ACL identity
rule, or the M6G export projection contract.

## 3. Terminology

- **Crawl run** — the durable unit of work that owns a fingerprint (§15), a
  raw-evidence generation (§13), inventory state, and checkpoint state
  (owner decision E). A crawl run persists across process restarts.
- **Process session** — the unit that owns the OS-level exclusive lock
  (§14) and session-level controls, including controlled stop (§16). One
  crawl run may span multiple process sessions.
- **Generation** — an immutable raw-evidence scope bound to exactly one
  crawl run, used to isolate raw artifacts produced by that run from raw
  artifacts produced by any other run (§13).
- **Logical request** — one bounded outbound HTTP request made against the
  Confluence API during a process session, subject to the future rate and
  retry policy owned by M7-A2.
- **Inventory occurrence** — one normalized inventory record persisted for a
  specific include root (§11); the same descendant page may have more than
  one inventory occurrence when include roots overlap.
- **Inventory window** — one paginated response window returned by a
  descendants search request, carrying its own observed `totalSize` (§5).
- **Checkpoint transition** — a durable advance of crawl-run state that may
  only be recorded after all rows for the corresponding window are
  durably persisted in the same transaction (§12, owner decision B).
- **Replay** — re-observing raw evidence within the same crawl run and
  generation that was already preserved by that run; identical replay is
  accepted, differing replay is a state conflict (§13).
- **Resume** — continuing a specific, already-existing crawl run through
  `resume_explicit_run_id` or `resume_unique_incomplete_run` (§10); resume is
  never inferred by selecting the newest incomplete run.

## 4. Execution model: single-worker, sequential M7-v1

M7-v1 executes as a single worker performing sequential logical requests
within a process session. No concurrent request pool, multi-worker
coordination, or parallel window fetch is in scope for M7-v1. This
constraint keeps checkpoint ordering (§12) and single-writer ownership (§14)
straightforward; a future multi-worker profile would require its own
contract and its own fingerprint dimension.

## 5. Per-window `totalSize` pagination authority

`totalSize` is evaluated independently for each response window, exactly as
in the approved M5B mapper. A crawl run never freezes an
`expected_total_size` value derived from an earlier window and never
rejects a later window solely because its `totalSize` differs from an
earlier one.

## 6. `totalSize` drift compatibility

`totalSize` drift between windows of the same descendants pagination
sequence is permitted and is recorded as observed fact, not corrected,
interpolated, or treated as an error. A crawl run's inventory result
reflects the sequence of windows actually observed, including any drift.

`_links.next` does not control terminal detection and does not control
resume. Terminal detection and the next request are always derived only from
the numeric fields of the current window, per owner decision A:
`next_start = response.start + response.size`; a window is terminal when
`next_start >= response.totalSize`.

## 7. Zero-size and bounded-window invariants

Consistent with the approved M5B mapper, every non-terminal window MUST
report a positive result count: a window with `start < totalSize` and a
zero-length result set is a payload contract violation, not a valid empty
page. Every window's result count MUST NOT exceed the requested page size
(`limit`). These two invariants hold for every inventory window regardless
of `totalSize` drift.

## 8. Crash-consistency guarantees and snapshot-isolation disclaimer

M7 guarantees crash consistency: after an interruption at any point, the
durable inventory state reflects only windows whose checkpoint transition
was fully committed (§12), and resuming a crawl run never durably records a
partial window. M7 explicitly does not guarantee upstream point-in-time
snapshot isolation. Because `totalSize` may drift between windows (§6) and a
crawl run may span an arbitrarily long wall-clock duration across multiple
process sessions, the resulting inventory is a crash-consistent record of
what was actually observed, not a proof that the upstream Confluence content
tree was frozen for the duration of the crawl.

## 9. Run and session separation

A crawl run and a process session are distinct durable/ephemeral concepts
(§3, owner decision E). The crawl run owns fingerprint, generation,
inventory, and checkpoint state and persists independent of any single
process's lifetime. The process session owns only the OS-level exclusive
lock (§14) and session-scoped controls such as controlled stop (§16). A
crawl run's identity and durable state are unaffected by how many process
sessions were used to advance it.

## 10. The three mutually exclusive run operations

Exactly three run operations exist, and no fallback path exists between
them (owner decision F):

1. `start_new_run` — creates a new crawl run under a newly constructed
   fingerprint (§15). It MUST NOT proceed if an incomplete run already
   exists under the same fingerprint; that condition is a caller-visible
   conflict, not a silent skip or a silent join.
2. `resume_explicit_run_id` — continues a specific, caller-identified crawl
   run. It fails closed if the identified run does not exist or is not in a
   resumable state.
3. `resume_unique_incomplete_run` — continues the single incomplete crawl
   run matching the current fingerprint. It fails closed on zero matches and
   fails closed on more than one match. It never selects the newest matching
   run automatically.

## 11. Overlapping-root support at the A1 level

Overlapping include roots remain supported (owner decision G), unchanged
from approved M5A/M5B behavior. Inventory occurrences are persisted per
include root, so root-relative ancestor paths for the same descendant page
may legitimately differ across overlapping roots. Final compatibility
between two inventory occurrences for what may be the same page is compared
as ordered pairs of `(ancestor_page_id, ancestor_title)`, never by page ID
alone. The detailed M7-C parent/path validation, stable-metadata comparison,
and longest-path canonicalization rule is authoritative in
`CHECKPOINT_RESUME_SPEC.md` section 9; it preserves the root-relative M5
mapping while treating `parent_page_id` as occurrence context. Detailed
deduplication mechanics are deferred to M7-A3a and are not defined here.

## 12. Durable inventory atomicity (contract level)

A future crawl run persists normalized inventory occurrences together with
cursor/terminal state for a window in one transaction (owner decision B). No
durable cursor advancement (checkpoint transition, §3) may become visible
unless every row for that window was persisted in the same transaction. This
section states the atomicity contract only; it defines no SQLite table,
column, or index. `sync_state.jsonl` is not, and does not become, the
authoritative mutable checkpoint database — it remains only an exported
snapshot/diagnostic representation, consistent with the existing Foundation
sync-state convention.

## 13. Raw-generation isolation (contract level)

Future raw artifacts produced by M7 are immutable and scoped to exactly one
crawl run and one generation (owner decision C). Within the same run and
generation, identical replay of previously preserved evidence is accepted.
Differing evidence observed for the same logical target within the same run
and generation is a state conflict and must not silently overwrite the
earlier evidence. A new crawl run may preserve changed evidence under a new
generation. This section states the isolation contract only; it defines no
store implementation, file layout, or serialization. Existing M6 fixed-path
raw artifacts (the M6A raw page store and the M6B restriction/attachment
observation stores) remain unchanged; M7 generations are additive alongside
them, not a replacement or reinterpretation of them.

## 14. OS process-lock ownership (contract level)

Crawl-run ownership during an active process session uses a
process-lifetime exclusive OS file lock (owner decision D). There is no
timestamp-based lease, no time-to-live expiry, and no automatic stale-lock
takeover. A process session that cannot acquire the lock must fail closed
rather than proceed against a run that may still be owned by another live
process. This section states the ownership contract only; it defines no
file-lock library or platform-specific mechanism.

For M7-C, lock scope and mutable checkpoint-workspace scope are identical. The
process acquires the exclusive lock before it opens, initializes, or mutates the
checkpoint database, and closes the database before releasing the lock. The
database and lock paths are derived together from one validated workspace
directory; callers cannot compose them independently.

## 15. Fingerprint ownership (contract level)

The crawl fingerprint is constructed by the system from the approved
effective configuration (owner decision K); callers never supply an
arbitrary fingerprint value directly. The fingerprint excludes the raw
source URL, credentials, the source ID, raw query text, and any local
filesystem path. A numeric profile change (§17, and the locked values in
`decision_logs/M7_OWNER_DECISIONS.md` §2.L) is a configuration change and,
because the fingerprint is derived from effective configuration, requires a
new `profile_version` and produces a new fingerprint. The offline-only
100,000-page scale profile is therefore independently versioned as
`m7-crawl-scale-acceptance-v2` / `"2"`; it does not revise the approved
production mapping. This section states fingerprint ownership and exclusions
only; exact canonicalization is deferred to M7-A3c.

## 16. Controlled-stop ownership (contract level)

Controlled stop occurs only after N committed checkpoints of one named kind,
and is evaluated only after a checkpoint transition's transaction has
successfully committed (owner decision J) — never mid-transaction. Controlled
stop governs the process session, not the crawl run, and is explicitly
excluded from the crawl fingerprint (§15): stopping and resuming a session
under a different controlled-stop setting does not change the run's
fingerprint or identity. Detailed acceptance behavior is deferred to M7-A3c.

## 17. Raw, request, and storage boundedness

The owner-locked numeric profile
(`crawl_reliability_profile.yaml`, matching
`decision_logs/M7_OWNER_DECISIONS.md` §2.L) bounds a future crawl run's
request volume, inventory scope, raw
evidence volume, and storage footprint, including per-run request ceilings,
per-root and per-run inventory-window ceilings, restriction/attachment
window ceilings, and raw byte/artifact/free-disk-reserve ceilings. M7-A2
materializes the profile as a contract artifact and defines its request/retry
semantics. Enforcement and runtime loading remain later reviewed production
work.

The separately versioned `crawl_reliability_scale_profile.yaml` is an offline
acceptance-only inventory-cap profile. It MAY be selected only for the 100,000-
page scale gate in `CRAWL_ACCEPTANCE_SPEC.md`; its version is `"2"` because its
numeric bounds differ from production. It preserves the production retry-policy
numeric/boolean parameters, while B2 remains exactly bound to the normal profile by
`RETRY_POLICY_SPEC.md`; no scale-profile value may alter that B2 binding.

## 18. Security and sanitized durable-evidence rules

Consistent with the existing Foundation security posture (M5/M6), M7 durable
evidence and documentation must never contain: a raw source URL or hostname,
credentials or credential material (including Bearer/PAT values), a
username, a local filesystem path, a real source ID, a real page ID, a
principal identifier, real page/document content, a full runtime hash, or a
machine identity. Future M7 restriction-evidence envelopes (owner decision
H) and raw-generation artifacts (§13) remain outside Git history, consistent
with the existing M6 raw/sidecar exclusion policy. Any future M7 review or
acceptance evidence follows the same sanitized-evidence rules already
established for M5C/M6/M6G reviews: aggregate counts and boolean gate
outcomes are acceptable, real identifiers and content are not.

## 19. A1/A2/A3 dependency order

M7 is decomposed directionally:

- **M7-A1 (this document):** owner decisions and this focused reliability
  contract, plus navigation/status synchronization only.
- **M7-A2:** contract-only failure taxonomy, retry/backoff/rate-limit
  semantics, deterministic acceptance matrix, and the
  `m7-crawl-reliability-v1` profile file, built against the numeric inputs
  locked in `decision_logs/M7_OWNER_DECISIONS.md` §2.L.
- **M7-A3 (a/b/c):** overlapping-root deduplication mechanics (M7-A3a),
  restriction-evidence envelope serialization (M7-A3b), and controlled-stop
  acceptance behavior plus fingerprint canonicalization (M7-A3c).

Later stages depend on the contract fixed here. The owner accepted M7-A1,
explicitly waived its independent-review gate, and subsequently approved the
complete M7-A2/A3 contract stack. The approved contract gate opens production
planning, but does not itself authorize production code changes.

## 20. M7-A1 owner-acceptance gate

The owner accepted the M7-A1 contract and explicitly waived its independent
review because the designated reviewer was unavailable. This waiver applies
only to M7-A1 and does not extend to M7-A2, M7-A3, or production work.

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

The complete A1/A2/A3 contract gate is accepted. The next task is production
implementation planning; implementation remains unauthorized until that plan
is reviewed and the owner separately authorizes the work.
