# Confluence Foundation Closeout Plan (text-first, OCR deferred)

## 0. How to use this document

Each work package `W0`-`W5` below is a separate task. Do not hand the whole
document to one implementer. W1+W2 are complete; W4 is the current code gate.

Prompts written so far:

| Package | Prompt file | Status |
|---|---|---|
| W0 | (inline below, historical) | **DONE** — `d25ea42`, merged in `764efa3` |
| W1+W2 | `docs/learning/W1W2_PROMPT_M10_OPERATOR_PIPELINE.md` | **DONE** — operator pipeline landed in `eb76648` |
| W3 | — | **RESOLVED**, no work needed |
| W4 | `docs/learning/W4_PROMPT_DELTA_SECOND_SYNC.md` | **CURRENT** — staged implementation with independent review gates |
| W5 | (operator runbook below) | blocked by W4; then runs on the main machine |

**W1 and W2 were merged after a first implementation attempt failed.** The
original W1 prompt contained a scope error: it assumed a raw generation root
alone is sufficient input. It is not — enumerating Draw.io media requires
`attachment_id` and `content_hash`, which live in the harness's
`drawio-state.json`, and that was scoped into W2. The split made W1
unbuildable. `W1_PROMPT_M10_OPERATOR_COMPOSITION.md` and
`W2_PROMPT_HARNESS_TO_M10_BINDING.md` are superseded and kept only for history.

The first attempt also produced two lessons now encoded in the merged prompt:
a CLI that parses arguments and discards them is not an operator path, and
`MaterializeConfluenceAcl` is **not** blocked by missing restriction evidence —
it has an explicit deny-safe `unavailable` path emitting
`["restricted:unresolved"]`.

Status labels used here:

- **verified** — confirmed by reading or running the code at the milestone head named in the relevant section.
- **assumed** — inferred, must be confirmed by the implementer before relying on it.

## 1. Goal

Close the Foundation Definition of Done for the **Confluence** source, text
first. OCR and broad binary-media processing stay deferred per
`docs/learning/CONFLUENCE_AUTOMATION_READINESS.md` section 8.

Definition of Done: one bounded real Confluence run produces a published M10
snapshot whose eight JSONL streams plus manifest are schema-valid,
cross-linked, ACL-safe, deterministic on repeat, and accepted by readback;
**plus** a second-sync delta proving changed, deleted, moved-out-of-scope, and
access-revoked entities.

That second clause is why W4 exists as its own package — a full snapshot alone
does not close Foundation.

## 2. Verified current state

### 2.1 Producers — all eight streams already exist

Every stream has a real production class. **verified**

| Stream | Producer |
|---|---|
| `documents`, `chunks` | `ProcessConfluencePageSet` |
| `relations` | `BuildConfluenceJiraRelations`, `MaterializeConfluenceMediaRelations` |
| `acl` | `MaterializeConfluenceAcl` |
| `media_assets` | `ProcessConfluenceMediaAttachment`, `ProcessConfluenceMediaBatch` |
| `sync_state` | `BuildSyncStateSnapshot` |
| `tombstones` | `ProjectTombstones` |
| `symbols` | Git-only; not produced by the Confluence path |
| handoff assembly | `AssembleConfluenceM10Handoff` |

### 2.2 Operator-runnable M10 full-snapshot path — closed by W1+W2

**verified at `eb76648`.** The merged W1+W2 implementation now:

- builds a real `M10SnapshotRequest` and production composition from parsed
  shell arguments;
- binds page order, run/generation identity, and selection identity to the
  subtree harness state instead of accepting a hand-written page list;
- composes the approved relation, deny-safe ACL, Draw.io media, sync-state,
  and handoff producers;
- publishes a deterministic eight-stream Confluence-only full snapshot while
  retaining a valid pinned, zero-row Git identity; and
- has a forcing test that drives harness state into `main(argv)` and exercises
  the Draw.io and ACL paths.

W1 and W2 are complete as one merged package. The original separate W1 and W2
prompt files remain historical only.

### 2.3 The remaining gap — sparse, evidence-bound second-sync delta

**verified.** More is already built than expected:

- `M10DeltaSnapshotExporter` exists and is fully wired internally — it
  constructs its own `M10DeltaOrchestrator`.
- It requires two inputs the full exporter does not: `prior_snapshot_reader`
  and `delta_inventory: tuple[DeltaInventoryEntry, ...]`.
- `PublishedSnapshotReader(dataset_root=, validator=)` is a concrete,
  production-ready `prior_snapshot_reader`.
- `DeltaInventoryState` already enumerates exactly the cases the Definition of
  Done requires: `PRESENT`, `SOURCE_DELETED`, `ACCESS_REVOKED`,
  `MOVED_OUT_OF_SCOPE`, plus `CONFIG_INVALIDATED`.

What is missing is (a) an operator path for delta mode, (b) evidence-bound
construction of `delta_inventory`, and (c) projection of a genuinely sparse
delta rather than republishing the full current projection with tombstones
appended. Publication-time readback must validate delta closure against the
accepted base snapshot. **W4 closes these gaps.**

### 2.4 Subtree harness (readiness doc Gate A) — landed

**verified.** `main` at `764efa3` contains `CORPUS-H1..H7`, the `H7-FIX-A..E`
stack, and this plan. All four review findings are closed and the branch is
merged.

Two production defects were caught and fixed along the way, both of which made
the live path unusable:

- **H7-FIX-D** — the operator page cap was written into the fingerprinted
  reliability profile, which only accepts two closed approved values, so every
  live phase failed unconditionally.
- **H7-FIX-E** — `activate_raw_generation`'s session never exposed
  `acknowledge_raw_page`, so `capture-pages` could not durably complete a
  single page. Caught by the new forcing end-to-end test.

The harness produces `documents.jsonl` / `chunks.jsonl` / `media_assets.jsonl`
/ `packet_summary.json`. It does **not** produce `relations`, `acl`, `symbols`,
`sync_state`, `tombstones`, or a manifest. It is a Gate A acceptance tool, not
the M10 snapshot path.

### 2.5 Confluence-only scope — settled

**verified by execution.** `M10SnapshotRequest` requires `git_repository`,
`git_branch`, and `git_commit` (40-hex), and `M10GitHandoff.__post_init__`
rejects an empty repository/branch or non-hex commit. But running the real
`M10FullSnapshotExporter` with an all-empty `M10GitHandoff` carrying a valid
pinned identity published successfully: `status == "published"`, counts
`{documents: 1, chunks: 1, relations: 1, acl: 1, media_assets: 0, symbols: 0,
sync_state: 1, tombstones: 0}`.

The first snapshot may pin a real repository/branch/commit and emit zero Git
rows. No contract change and no operator decision required.

### 2.6 Test baseline at `764efa3`

`tests/foundation` — **3264 passed, 40 skipped, 9 errors**.
`tests/shared tests/architecture` — **117 passed**.

All nine errors are asset-backed BGE-M3 tests that `pytest.fail` without
`--tokenizer-assets-dir`. The pinned bundle is not on the review machine.
Report them as **not run**, never as failures, and never satisfy them with an
implicit Hugging Face cache.

## 3. What each stage actually buys you

| Capability | after W1 | +W2 | +W4 | +W5 |
|---|---|---|---|---|
| Live crawl → raw generation | yes | yes | yes | yes |
| Raw generation → 8-stream snapshot | yes | yes | yes | yes |
| The two halves provably connect | no | yes | yes | yes |
| Second-sync delta | no | no | yes | yes |
| Real-input evidence | no | no | no | yes |

**W1+W2** = one full live pass to an eight-stream snapshot. In readiness-doc
language that is *"Controlled full-text crawl ready"* plus gate F5. It is
**not** Foundation complete — F6 (delta) is still open until W4.

Even after W5 this is **not** *"Automatic recurring Confluence crawl ready"*;
that additionally needs readiness Gate B (scheduler, quarantine, retention,
observability).

## 4. Work packages

### W0 — Close the Gate A harness review findings and land it — **DONE** (`d25ea42`, merged `764efa3`)

Closed P1-2 (forcing end-to-end test across all five phases), P2-1 (export
re-verifies Draw.io raw bytes on disk), P2-3 (every selection row is
source-version-bound), P3-1 (root page asserted present in the published
selection), plus the `acknowledge_raw_page` defect described in §2.4.

---

### W1+W2 — Operator-runnable Confluence M10 full snapshot — **DONE** (`eb76648`)

Historical implementation prompt:
`docs/learning/W1W2_PROMPT_M10_OPERATOR_PIPELINE.md`

Build the four missing Confluence stages (relation, acl, media, sync
inventory) plus an operator CLI that turns a preserved raw generation into a
published eight-stream snapshot.

**Exit:** `--help` works, and an offline test publishes a full eight-stream
snapshot plus manifest from fixture raw evidence, twice, deterministically —
including a Confluence-only run with zero Git records.

---

### W2 — Bind the subtree harness generation to the M10 request — **DONE with W1**

The separate prompt is superseded. Its requirements were incorporated into
`docs/learning/W1W2_PROMPT_M10_OPERATOR_PIPELINE.md` and landed with W1.

The harness produces a raw generation; the W1 CLI consumes one. Nothing yet
proves they agree on `ordered_page_ids`, `raw_generation_id`, the raw page
layout, or — the real risk — the Draw.io attachment layout.

**Exit:** one offline test drives the harness end to end over a fake transport
and then runs the W1 CLI over the resulting generation, with no manual
translation step.

---

### W3 — Confluence-only scope resolution — **RESOLVED, no work needed**

See §2.5. W1 carries this as a settled input.

---

### W4 — Operator-runnable second-sync delta — **CURRENT**

Prompt: `docs/learning/W4_PROMPT_DELTA_SECOND_SYNC.md`

Wire `M10DeltaSnapshotExporter` behind an operator path and build the
`delta_inventory` classification against a prior accepted snapshot. Required by
the Foundation Definition of Done; W1 covers `full_snapshot` only.

**Exit:** an offline test publishes a full snapshot, then a delta bound to it,
proving changed, deleted, moved-out-of-scope, and access-revoked documents and
correct tombstone cascade.

---

### W5 — Real-input gates (operator, main machine)

These need real credentials and the pinned tokenizer bundle, so they cannot run
on the review machine.

Prerequisites:

- `CONFLUENCE_BASE_URL`, `CONFLUENCE_PAT` (environment / secret store).
- The pinned BGE-M3 bundle: `tokenizer.json`, byte size `17098108`, sha256
  `21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08`, from
  `BAAI/bge-m3` commit `5617a9f61b028005a4858fdac845db406aefb181`. External
  directory only; implicit Hugging Face cache is forbidden
  (`contracts/foundation/embedding_profile.yaml`).
- Real `--space-key` and `--root-page-id` for Root 1.

Steps:

1. **Gate A acceptance** (readiness doc §5, A7). Offline fault injection; small
   live tree; controlled stop after several batches; explicit resume of the
   same run; prove no refetch of committed windows/pages; deterministic repeat
   from the same raw generation; raw evidence unchanged by processing/export;
   sanitized logs.
2. **F4 media gate, minus OCR.** Text-first means **Draw.io only** — do not
   enable `image_only_pdf`, `image`, or `chart_screenshot`. Convert processor
   results to `SanitizedMediaProcessorOutcome`/`SanitizedMediaProcessorRun` and
   evaluate with `EvaluateBoundedMediaCorpusAcceptance`. The gate requires
   `real_capture_attested: true` and `transport: "production"`.

   **Open question, unresolved:** the current media-gate evaluator may expect
   all five media kinds. If it does, a text-first Draw.io-only gate needs an
   explicit reviewed variant — do **not** silently relax a threshold. This will
   only surface on a real run.
3. **F5 first real full snapshot.** Run the W1 CLI twice over the same raw
   generation. Verify determinism, all eight JSONL files plus manifest, exact
   counts, relation/media/ACL/sync closure, atomic publication and no-clobber
   rollback. Retain only sanitized readback metadata.
4. **F6 second-sync delta.** Use the first snapshot as prior state; prove
   changed, deleted, moved-out-of-scope, and access-revoked entities; verify
   tombstone cascade to chunks, media, relations, and ACL; verify an ACL-only
   change re-emits ACL/chunks without inventing content tombstones.

**Exit:** Foundation complete for Confluence, text-first.

## 5. Explicitly out of scope

- OCR and any image/PDF/audio/video processing (readiness doc §8).
- `attachment_text` chunks (blocked by D20).
- Readiness Gate B (unattended scheduling, quarantine, retention,
  observability) and Gate C (concurrency, parallelism).
- The B1 *efficiency* optimization — skipping body fetch for unchanged pages.
  W4 needs delta **correctness**, not incremental-fetch optimization; a second
  full crawl compared against the prior snapshot satisfies F6.
- Root 2 / HQ root — starts only after Root 1 is accepted.
- Embeddings, Qdrant, retrieval, PLM.

## 6. Guardrails for every work package

From `AGENTS.md`:

- Independent reviewers never edit files; a re-review runs in a new session.
- Every public/application boundary needs an adversarial negative pass:
  `object()`, `None`, wrong enum values, missing required fields, forbidden
  extra fields, impossible counters. Type annotations are not runtime
  validation.
- Never read, print, commit, or transmit `.env`, `.local_ai/evidence/`,
  `Tool_TRreport/`, raw runtime data, credentials, or unsanitized Confluence
  content.
- Implementers change only what the plan requires and report exact commands and
  results.
- Do not weaken, bypass, or special-case existing validation to make a test
  pass. If a contract genuinely blocks the task, stop and report it.
