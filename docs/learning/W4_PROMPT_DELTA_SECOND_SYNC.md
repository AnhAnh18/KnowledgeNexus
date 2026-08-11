# W4 implementation prompt — evidence-bound sparse second-sync delta

`RECOMMENDED_IMPLEMENTATION_PROFILE: complex`

This is the active W4 prompt. It supersedes every earlier version of the W4
prompt and must be used by itself. Do not combine it with the historical W1,
W2, or W1+W2 prompts.

Implementer: Codex GPT-5.6-Sol

Independent reviewer: the Codex session that authored this plan. The reviewer
must not implement or fix W4 code.

## 1. Current milestone state

The repository state before this plan is:

```text
W0: complete
W1+W2: complete — operator-runnable M10 full snapshot landed in eb76648
W3: resolved — no implementation required
W4: current
W5: blocked by W4
```

W1+W2 already proves, offline, that the subtree harness generation and its
state artifacts can be composed into a deterministic, published, eight-stream
M10 full snapshot. Do not redesign that path.

Before starting:

```text
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status --short
```

Require a clean tracked worktree and verify that `eb76648` is an ancestor of
`HEAD`. The current plan commit is documentation-only and will be on top of
that production head. Create a new review branch named `review/w4-delta-second-sync`.
Do not work on a detached or dirty main checkout.

Do not read, print, commit, or transmit `.env`, `.local_ai/evidence/`,
`Tool_TRreport/`, raw/runtime data, credentials, or unsanitized Confluence
content.

## 2. Read these files before designing

Read each selected file completely, not only the class signatures:

```text
contracts/foundation/START_HERE.md
contracts/foundation/CHUNKING_SPEC.md
contracts/foundation/RAW_GENERATION_SPEC.md
contracts/foundation/schemas/manifest.schema.json
contracts/foundation/schemas/tombstone_record.schema.json
contracts/foundation/schemas/sync_state_record.schema.json
contracts/foundation/decision_logs/AI_Knowledge_Platform_Master_Spec_v7_1.md
  especially sections 16.2 and 18.1–18.3
contracts/foundation/decision_logs/AI_Knowledge_Platform_v7_4_Update.md
  especially the moved-out-of-scope decision

docs/learning/CONFLUENCE_FOUNDATION_CLOSEOUT_PLAN.md
docs/learning/CONFLUENCE_AUTOMATION_READINESS.md
docs/learning/W1W2_PROMPT_M10_OPERATOR_PIPELINE.md

src/knowledgenexus/foundation/cli/export_m10_snapshot.py
src/knowledgenexus/foundation/cli/confluence_subtree_corpus.py
src/knowledgenexus/foundation/domain/models/m10_snapshot.py
src/knowledgenexus/foundation/domain/models/delta_propagation.py
src/knowledgenexus/foundation/domain/models/tombstone_propagation.py
src/knowledgenexus/foundation/application/use_cases/export_m10_snapshot.py
src/knowledgenexus/foundation/application/use_cases/project_m10_delta.py
src/knowledgenexus/foundation/application/use_cases/propagate_delta.py
src/knowledgenexus/foundation/application/use_cases/project_tombstones.py
src/knowledgenexus/foundation/infrastructure/exporters/m10_snapshot_exporter.py
src/knowledgenexus/foundation/infrastructure/exporters/delta_snapshot_reader.py
src/knowledgenexus/foundation/domain/rules/snapshot_readback.py
src/knowledgenexus/foundation/infrastructure/confluence/
  confluence_subtree_live_composition.py
src/knowledgenexus/foundation/infrastructure/confluence/
  confluence_retrying_http_transport.py
src/knowledgenexus/foundation/infrastructure/checkpoint/
  sqlite_checkpoint_run_registry.py

tests/foundation/application/use_cases/test_propagate_delta.py
tests/foundation/application/use_cases/test_project_m10_delta.py
tests/foundation/application/use_cases/test_export_m10_snapshot.py
tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py
tests/foundation/domain/rules/test_snapshot_readback.py
tests/foundation/cli/test_export_m10_snapshot_cli.py
tests/foundation/cli/test_m10_operator_cli_e2e.py
tests/foundation/cli/test_confluence_subtree_cli.py
```

Inspect nearby models, ports, stores, and tests when one of these files routes
you there. Do not infer a constructor or durable-state shape from this prompt
when the repository can answer it.

## 3. Verified defects and gaps at the W4 base

These are verified facts, not optional review suggestions:

1. `export_m10_snapshot.py` parses `--export-mode delta` and
   `--base-dataset-version`, but its production `run()` still constructs a
   `M10FullSnapshotExporter`. The delta CLI surface is not wired.

2. `M10DeltaSnapshotExporter`, `PublishedSnapshotReader`,
   `M10DeltaOrchestrator`, `PropagateDelta`, and `ProjectTombstones` already
   exist. Reuse them; do not build parallel exporters or tombstone engines.

3. `M10DeltaOrchestrator` currently appends generated tombstones to the full
   current projection. It does not project a sparse delta. A delta that repeats
   every unchanged current record violates the master contract.

4. Publication acceptance calls `validate_snapshot_streams(...,
   export_mode="delta")` without the accepted base streams. The current
   validator also requires all parents to be present inside the delta itself.
   Consequently, a correct sparse ACL-only delta cannot pass acceptance even
   though the master contract requires ACL and chunk re-emission without a
   content tombstone.

5. `PropagateDelta` currently treats a prior document missing from the current
   projection and absent from `delta_inventory` as `SOURCE_DELETED`. Absence
   alone is not deletion evidence. W4 must remove this unsafe fallback for the
   production M10 delta path.

6. Master spec section 18.2 requires a 404 deletion observation to retain the
   ambiguity that some Confluence versions use 404 for inaccessible pages.
   `DeltaInventoryEntry` currently has no `detail`, so that requirement cannot
   reach the document tombstone.

7. The current subtree selection contains included pages. It cannot by itself
   distinguish deletion, access revocation, and movement out of scope for a
   page that existed in the prior accepted snapshot.

Do not hide any of these facts behind a passing unit test.

## 4. W4 goal

Build an operator-runnable, evidence-bound second-sync path:

```text
accepted base M10 snapshot
+ complete second-run inventory/selection
+ preserved current raw generation and harness state
+ preserved disposition observations for prior pages missing from selection
→ strict DeltaInventoryEntry set
→ current full in-memory projection
→ sparse delta projection
→ deterministic published delta bound to base_dataset_version
```

The published delta must contain only new or changed records plus tombstones.
It must be applicable as tombstones-first, then upsert-by-ID, to the accepted
base snapshot.

W4 proves correctness, not incremental-fetch efficiency. A second run may
inventory and fetch all currently in-scope pages. Skipping unchanged body
fetches remains Automation Readiness Gate B1.

## 5. Locked classification semantics

Use the master contract literally:

| Evidence for a prior Confluence page | Delta inventory state |
|---|---|
| Page is in the complete current selection | `PRESENT` |
| Missing from current selection; direct page GET is 404 | `SOURCE_DELETED` |
| Missing from current selection; direct page GET is 403 | `ACCESS_REVOKED` |
| Missing from selection; GET is 200; current ancestor/exclusion evaluation proves it is outside scope | `MOVED_OUT_OF_SCOPE` |

Additional locked rules:

- A 404-derived `SOURCE_DELETED` entry must carry the exact non-sensitive
  detail value `confluence_404_may_mask_access_revoked`, and that detail must
  appear on the document tombstone.
- This rule applies to a direct **page-content GET** performed only after the
  page is absent from a complete current inventory. It does not change M6B's
  restriction-endpoint rule: restriction 404 remains `unavailable` and must
  never be interpreted as unrestricted or as page deletion.
- 401 is an operator/credential failure, not page-level access revocation.
  Fail the classification phase without publishing a disposition.
- Retryable and unexpected statuses remain governed by the approved M7 retry
  policy. If retries terminate, fail the phase; do not invent a state.
- A 200 response for a page that remains under an include root and matches no
  approved exclusion contradicts the supposedly complete inventory. Fail as
  `inventory_inconsistent`; do not classify it as deleted or moved.
- Direct page ID exclusions and excluded-subtree ancestry both produce
  `MOVED_OUT_OF_SCOPE` only when the current approved scope proves them.
- `CONFIG_INVALIDATED` is derived internally from accepted base/current
  configuration identity. It is never accepted as an operator-authored page
  disposition.
- A chunker-version mismatch remains a hard failure at the existing
  orchestrator guard. Do not compare incompatible chunk semantics.
- Every prior and current Confluence document must have exactly one validated
  inventory entry. No missing entry may default to deletion.
- W4 is Confluence-only. The pinned Git identity remains valid but Git streams
  must be empty. Fail closed if the accepted base or current handoff contains
  Git records; Git delta classification is a separate task.

## 6. Durable disposition evidence

Add a focused contract, named
`contracts/foundation/DELTA_SECOND_SYNC_SPEC.md`, and link it from
`contracts/foundation/START_HERE.md`. It must define one versioned,
generation-scoped `delta-inventory.json` artifact and the raw probe evidence
that supports it.

The exact representation may follow existing raw-envelope conventions, but
the contract and implementation must guarantee all of the following:

- format version, run ID, generation ID, current selection identity, accepted
  base dataset version, and canonical current scope identity are bound;
- each prior/current Confluence document is represented exactly once;
- `document_id` is re-derived from `page_id`, never trusted independently;
- removed-page `source_version_last_seen` equals the accepted base document's
  source version;
- every direct probe records the observed HTTP status and binds to preserved
  exact response bytes by byte count and SHA-256;
- raw probe evidence is published before the derived disposition is
  checkpointed;
- writes are atomic, no-clobber, generation-scoped, path-safe, and reject
  symlink/reparse traversal;
- replay verifies existing bytes and reuses matching evidence without a
  second GET; conflicts fail closed;
- response byte, request, artifact, and free-disk limits reuse the active M7
  reliability profile; no W4 hardcoded budget is allowed;
- raw bodies, page IDs, paths, hashes, URLs, titles, principals, and
  credentials never appear in CLI output or durable review summaries.

Do not store only a self-reported state such as `source_deleted`. Preserve the
status/body observation first and derive the state from it.

## 7. Sparse delta semantics

The delta projector must compare records by their stable identity field and
canonical JSON bytes. It must not mutate input projections.

Required behavior:

- **New document:** emit the new document and all of its current dependent
  records.
- **Unchanged document:** emit nothing.
- **Content changed:** emit the changed document; emit only new or byte-changed
  current records; tombstone removed chunk/dependent IDs with the existing
  approved producers.
- **Deleted, access-revoked, or moved:** emit no current records for the page;
  tombstone the prior document and cascade to its prior chunks, media,
  relations, and ACL.
- **ACL-only change:** emit the changed ACL record and every affected current
  chunk with updated `acl_tags`; emit no content tombstone. Do not emit an
  unchanged document merely to satisfy the old local-only closure check.
- **Config invalidation with compatible chunk semantics:** tombstone invalid
  prior entities with `config_invalidated` and emit the required current
  replacements. Tombstones are applied before upserts by the consumer.
- Metrics and manifest counts describe emitted delta rows, not the effective
  post-apply corpus size.
- Ordering is deterministic by the established stream identity rules.

Update readback/acceptance so a sparse delta is validated against the exact
accepted base read during orchestration. Validation must construct or reason
about the effective overlay:

```text
base streams
→ apply delta tombstones
→ upsert delta rows by stable ID
→ validate effective cross-stream closure
```

The same accepted base bytes must underpin classification, projection, and
publication acceptance. Avoid a verify/read time-of-check/time-of-use gap.
Do not weaken full-snapshot validation or alter existing golden full-snapshot
bytes.

## 8. Operator composition

Extend the existing seams instead of creating a second crawler:

1. Add one bounded second-sync disposition phase to the subtree operator. It
   consumes the accepted base snapshot and the complete current selection,
   probes only prior Confluence pages missing from that selection through the
   approved status-aware retry/checkpoint transport, preserves raw evidence,
   and atomically publishes `delta-inventory.json`.
2. Keep `export_m10_snapshot` offline. In delta mode it consumes the preserved
   raw generation, harness state, accepted base snapshot, and the bound
   `delta-inventory.json`; it performs no network call.
3. Require `--base-dataset-version` and the bound delta-inventory artifact in
   delta mode. Reject both in full-snapshot mode unless an existing compatible
   argument is already required there.
4. Instantiate `PublishedSnapshotReader` and `M10DeltaSnapshotExporter` for
   delta mode. Never send a delta request to `M10FullSnapshotExporter`.
5. Preserve the existing injected `run(...)`/`main(...)` test seam and the
   sanitized exit taxonomy:

```text
1 unexpected
2 configuration
20 invalid_request
21 adapter
15 projection
16 staging
17 completion
18 publication
19 acceptance
```

No successful or failed CLI output may expose source identifiers or content.

## 9. Mandatory staged decomposition

W4 is intentionally split to prevent another unreviewable cross-cutting
commit. Do not combine these stages and do not squash their history.

### W4-A — contract, evidence model, and pure classifier

Allowed scope:

- focused delta second-sync contract and `START_HERE` registration;
- runtime-validated domain models, failure vocabulary, and ownership-isolated
  result models (`frozen=True, repr=False` where sensitive data is retained);
- pure classification use case over injected observations;
- propagation of 404 ambiguity detail into document tombstones;
- focused domain/application/architecture tests.

No filesystem store, HTTP adapter, CLI wiring, sparse projection, or exporter
change in W4-A.

The pure application boundary should be equivalent to:

```text
accepted prior Confluence document records
+ current bound inventory selection
+ current include/exclude scope
+ raw-status disposition observations for prior pages missing from selection
→ sorted tuple[DeltaInventoryEntry, ...] plus aggregate metrics
```

Do not accept caller-preclassified `source_deleted`, `access_revoked`, or
`moved_out_of_scope` strings as authority. The classifier derives the state
from status plus scope facts. Its observation model must retain at least:

```text
page_id
http_status
ancestor_page_ids
response_byte_count
response_sha256
source_version_last_seen
```

The result must be ownership-isolated and non-revealing under `repr`. Use a
small sanitized failure vocabulary with distinct categories for invalid input,
invalid prior snapshot, invalid selection/scope, invalid observation,
incomplete evidence, inventory inconsistency, invalid result, and internal
failure. Exceptions and CLI output must expose the category only.

Create candidate commit:

```text
[W4-A] foundation: define evidence-bound delta inventory classification
```

Push only the review branch and stop for independent review. Current owner
authorization covers W4-A only.

### W4-B — sparse projection and base-aware acceptance

Start only after W4-A receives an independent `Approve` verdict and its head is
frozen.

Allowed scope:

- remove the unsafe missing-inventory deletion fallback from the M10 delta
  path;
- project sparse per-stream deltas;
- make readback/publication acceptance validate against the exact base;
- preserve full-snapshot behavior and golden bytes;
- focused propagation/orchestrator/readback/export tests.

Candidate commit:

```text
[W4-B] foundation: project and validate sparse M10 deltas
```

Push the review branch and stop again.

### W4-C — durable probe capture and operator wiring

Start only after W4-B is independently approved and frozen.

Allowed scope:

- generation-scoped raw probe store and state artifact;
- status-aware disposition adapter using the existing M7 retry/checkpoint
  activation and reliability profile;
- subtree disposition phase;
- offline delta export CLI wiring;
- forcing end-to-end tests through real `main(argv)` argument lists.

Candidate commits may be split into:

```text
[W4-C1] foundation: preserve second-sync page disposition evidence
[W4-C2] foundation: expose operator-runnable M10 delta publication
```

Do not create W4-D closeout docs, merge to main, or start W5.

## 10. Forcing and adversarial tests

The final W4 stack must prove all of these:

1. Publish a full snapshot, produce a second generation, then publish a delta
   bound to the first snapshot through CLI `main(argv)`.
2. New, content-changed, source-deleted, access-revoked, and
   moved-out-of-scope pages each produce the exact sparse stream/tombstone
   behavior.
3. A 404 produces `source_deleted` with
   `detail="confluence_404_may_mask_access_revoked"`.
4. A 403 produces `access_revoked`; 401 and exhausted retryable statuses fail
   without a disposition.
5. A fetchable still-in-scope page missing from the complete inventory fails
   as inconsistent.
6. ACL-only change emits ACL plus affected chunks, no content tombstone, and
   no unchanged document.
7. Removed relations/media/ACL/chunks cascade correctly.
8. An entirely unchanged second sync publishes a valid empty sparse delta.
9. Two equivalent runs into separate fresh dataset roots produce byte-identical
   version directories and identical digest/dataset version.
10. The base snapshot, raw generation, probe evidence, selection, and harness
    state remain byte-identical before/after offline projection/export.
11. Full-snapshot golden output remains byte-identical.
12. No network is possible in the export phase. The capture test uses only a
    fake transport; no live request is authorized during implementation.
13. Raw probe replay performs no second GET; conflicting evidence fails.
14. Run/generation/selection/base/scope mismatch, duplicate IDs, missing prior
    page evidence, malformed status/body, wrong enum, bool-as-int, forbidden
    extra fields, impossible counters, relative paths, symlinks/reparse points,
    stale base version, incompatible chunker version, and publication collision
    all fail closed with sanitized categories.
15. `object()` and `None` at every new public boundary do not leak raw
    `AttributeError`, `KeyError`, `TypeError`, paths, content, or traceback.

Tests must have forcing teeth: each key test should fail against the W4 base,
not merely assert a self-reported success boolean.

## 11. Verification matrix

For each stage, run its focused tests plus the affected existing suites. Before
requesting final W4 review, run at least:

```text
python -m pytest \
  tests/foundation/application/use_cases/test_propagate_delta.py \
  tests/foundation/application/use_cases/test_project_m10_delta.py \
  tests/foundation/application/use_cases/test_export_m10_snapshot.py \
  tests/foundation/infrastructure/exporters/test_delta_snapshot_reader.py \
  tests/foundation/domain/rules/test_snapshot_readback.py \
  tests/foundation/cli/test_export_m10_snapshot_cli.py \
  tests/foundation/cli/test_m10_operator_cli_e2e.py \
  tests/foundation/cli/test_confluence_subtree_cli.py \
  tests/architecture -q

python -m compileall -q src tests
git diff --check <W4_BASE>..HEAD
git status --short
```

Then run:

```text
python -m pytest tests/foundation tests/shared tests/architecture -q
```

If the exact external BGE-M3 bundle is available, pass its explicit directory
with `--tokenizer-assets-dir` and keep Hugging Face/Transformers offline. If it
is unavailable, do not use an implicit cache and do not describe asset-backed
tests as passed. Run the non-asset matrix with the known asset-backed files
explicitly excluded, list those exact exclusions, and report them as not run.

Environment:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
PYTHONUTF8=1
```

## 12. Out of scope

- no live Confluence execution during implementation;
- no W5 operator evidence or closeout;
- no scheduler, quarantine, retention, or unattended recurring crawl;
- no HTTP concurrency or parallel crawl optimization;
- no incremental-fetch optimization for unchanged pages;
- no OCR, PDF/image/audio/video extraction, or `attachment_text` chunks;
- no embedding, Qdrant, retrieval, or chat code;
- no schema weakening and no reimplementation of approved M10/tombstone logic.

## 13. Stop and report rules

Stop rather than guessing if:

- the accepted base cannot be bound to the same bytes throughout projection
  and acceptance;
- the current durable run cannot safely expose the checkpoint activation
  required for missing-page probes;
- moved-out-of-scope cannot be proven from current ancestors plus approved
  exclusions;
- a required sparse delta cannot be represented without a contract/schema
  change not described here; or
- an existing active contract contradicts a locked rule above.

At each review stop, report:

```text
base full SHA
candidate full SHA
commit list
exact changed files
exact test commands/results
P0–P3 self-findings
boundary confirmation
git diff --check result
tracked worktree status
confirmation: no live request, no merge, no raw/evidence committed
```

Do not continue automatically past a mandatory independent-review gate.
