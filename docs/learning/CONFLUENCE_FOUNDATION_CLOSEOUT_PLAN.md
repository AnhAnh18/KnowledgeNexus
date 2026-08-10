# Confluence Foundation Closeout Plan (text-first, OCR deferred)

## 0. How to use this document

Each work package `W0`-`W4` below is written to be handed to a codex
implementer as a standalone prompt. Do not hand the whole document as one
task. Run them in order; `W1` is the critical path.

Status labels used here:

- **verified** - confirmed by reading the code on `review/confluence-root1-h1-h4`
  at `7eedef9` and `origin/main` at `9b64044`.
- **assumed** - inferred, must be confirmed by the implementer before relying on it.

## 1. Goal

Close the Foundation Definition of Done for the **Confluence** source, text
first. OCR and broad binary-media processing stay deferred per
`docs/learning/CONFLUENCE_AUTOMATION_READINESS.md` section 8.

Definition of Done for this plan: one bounded real Confluence run produces a
published M10 snapshot whose eight JSONL streams plus manifest are
schema-valid, cross-linked, ACL-safe, deterministic on repeat, and accepted by
readback; plus a second-sync delta proving changed / deleted / moved-out-of-scope
/ access-revoked cases.

## 2. Verified current state

### 2.1 Producers - all eight streams already exist

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

Composition and export seams also exist: `ConfluenceM10CompositionRoot.build()`,
`ConfluenceM10Adapter`, `M10FullSnapshotExporter`.

### 2.2 The actual gap - no operator-runnable M10 path

This is the critical finding. **verified**

- `ConfluenceM10CompositionRoot` is referenced **only from tests**
  (`tests/foundation/infrastructure/adapters/test_m10_composition_root.py`).
  No production code constructs it.
- `ConfluenceM10CompositionRoot.build()` accepts `relation_stage`, `acl_stage`,
  `media_stage`, `sync_inventory_stage` as **already-built** objects defaulting
  to `None`. It does not construct them. Something must.
- `src/knowledgenexus/foundation/cli/export_m10_snapshot.py` **cannot be run
  from a shell**. Its `_parse_args` calls `parser.parse_args([])` and returns an
  empty `Namespace`; `request`, `confluence_adapter`, and `git_adapter` are
  Python-injected keyword arguments. Invoking `python -m ...export_m10_snapshot`
  returns `invalid_request` (exit 20) because all three are `None`.
- `docs/FOUNDATION_EXTERNAL_GATE_RUNBOOK.md` acknowledges this: "the production
  harness must construct `ConfluenceM10Adapter`/`GitM10Adapter` over approved
  source ports, then call `M10FullSnapshotExporter.execute(request)` twice."
  **That harness does not exist.**

So: every part is built, nothing wires them into a command an operator can run.
This is why no real full-snapshot evidence exists yet.

### 2.3 Subtree corpus harness (readiness doc Gate A)

**verified**

- `origin/main` at `052b6e8` has the initial harness.
- `review/confluence-root1-h1-h4` adds `CORPUS-H1`..`H7`, the `H7-FIX-A/B/C`
  stack, and `H7-FIX-D` (`7eedef9`). **Not merged into main.**
- `H7-FIX-D` repaired a P0 that made all three live phases (`inventory`,
  `capture-pages`, `capture-drawio`) fail unconditionally: the operator page cap
  was being written into the fingerprinted reliability profile, which only
  accepts two closed approved values.
- The harness produces `documents.jsonl` / `chunks.jsonl` / `media_assets.jsonl`
  / `packet_summary.json`. It does **not** produce `relations`, `acl`,
  `symbols`, `sync_state`, `tombstones`, or a manifest. It is a Gate A
  acceptance tool, **not** the M10 snapshot path.

### 2.4 Open review findings on the harness

From the independent H7-FIX review, still unfixed:

- **P1-2** - no end-to-end test running all five phases sequentially against one
  state dir and run id. Phases pass individually; the sequence is unproven.
- **P2-1** - `export` publishes Draw.io media assets from `drawio-state.json`
  without re-reading the raw attachment bytes. A deleted or truncated artifact
  still yields a packet claiming `drawio_assets_failed: 0`.
- **P2-3** - `expected_source_version: null` passes through unbound for pages
  with no Draw.io intents.
- **P3-1** - the configured root page id is never independently asserted to be
  present in the published selection.

### 2.5 Scope constraint discovered - Git identity is mandatory

**verified.** `M10SnapshotRequest` requires `git_repository`, `git_branch`, and
`git_commit` (must match a 40-hex commit). `M10GitHandoff.__post_init__`
rejects an empty repository, branch, or non-hex commit.

The record tuples themselves (`documents`, `chunks`, `symbols`, ...) appear to
permit being empty. **assumed** - the implementer must confirm that
`M10FullSnapshotExporter` accepts a Git handoff carrying a valid pinned identity
with zero records, and that manifest/closure checks tolerate zero Git rows.

**Recommended default:** run Confluence-only by pinning a real repository,
branch, and commit while emitting zero Git records. If the exporter rejects
this, W3 becomes blocking and the decision escalates to the operator.

## 3. Work packages

### W0 - Close the Gate A harness review findings and land it — DONE (`d25ea42`)

All four findings closed. The forcing end-to-end test also caught a real
production defect it was written to catch: `activate_raw_generation`'s session
never exposed `acknowledge_raw_page`, so `capture-pages` could not durably
complete a single page in production. Fixed by adding the missing delegation
on `_RunActivated` and `_PublicActivation`.

Still open from W0: the branch is **not yet merged into `main`**.

**Prompt for codex (historical):**

> Branch `review/confluence-root1-h1-h4` at `7eedef9`. Close these findings from
> the independent CORPUS-H7-FIX review. Do not broaden scope.
>
> 1. **P1-2 (required).** Add one forcing end-to-end test that runs all five
>    phases of `knowledgenexus.foundation.cli.confluence_subtree_corpus`
>    sequentially - `inventory`, `capture-pages`, `process-pages`,
>    `capture-drawio`, `export` - against a single `--state-dir` and one run id,
>    with a fake/injected transport and no network. Assert the run id, selection
>    identity, and processing state thread correctly across all five, that the
>    published packet contains the root page, and that re-running each phase is
>    idempotent. This test must fail if any phase-to-phase handoff regresses.
> 2. **P2-1 (required).** Make `_export_phase` re-verify each Draw.io media
>    asset against its raw attachment artifact on disk before publication,
>    instead of trusting `drawio-state.json` records. Record enough binding in
>    the state (attachment id and/or content hash) to make this check exact.
>    A deleted, truncated, or modified raw body must fail the export closed.
> 3. **P2-3 (required).** Reject or explicitly bind a selection row whose
>    `expected_source_version` is null, so the selection is source-version-bound
>    for every page, not only pages carrying Draw.io intents.
> 4. **P3-1 (recommended).** Assert that the configured `--root-page-id` appears
>    in the published inventory selection.
>
> Per AGENTS.md every changed public boundary needs an adversarial negative pass
> (wrong runtime types, `None`, missing fields, impossible counters), not only
> happy-path coverage. Run the focused subtree, checkpoint, port, shared, and
> architecture tests and report exact commands and results. Do not run live
> Confluence requests.

**Exit:** all four closed, full `tests/foundation`, `tests/shared`,
`tests/architecture` green, branch merged to `main`.

---

### W1 - Operator-runnable Confluence M10 snapshot composition (critical path)

This is the single largest gap and everything downstream depends on it.

**Prompt for codex:**

> There is no way for an operator to produce an M10 snapshot. `ConfluenceM10CompositionRoot`
> is used only by tests, and `cli/export_m10_snapshot.py` parses no arguments and
> requires Python-injected adapters.
>
> Build one production composition plus operator CLI that turns a preserved
> Confluence raw generation into a published M10 full snapshot. Compose the
> existing approved use cases; do not reimplement HTTP, normalization, chunking,
> ACL, relation, media, sync, or export logic.
>
> Stages to construct and pass into `ConfluenceM10CompositionRoot.build()`:
> `ProcessConfluencePageSet` (page), `BuildConfluenceJiraRelations` +
> `MaterializeConfluenceMediaRelations` (relation), `MaterializeConfluenceAcl`
> (acl), the approved media stage (`ProcessConfluenceMediaBatch` /
> `ProcessConfluenceMediaAttachment`), `BuildSyncStateSnapshot` (sync inventory),
> and `ProjectTombstones` where the export mode requires it. Build the Git
> adapter via `GitM10CompositionRoot`.
>
> The CLI must accept real absolute-path arguments (raw generation root, run id,
> generation id, chunking profile path, tokenizer assets dir, Jira relation
> profile, dataset root, ordered page ids / selection path, Confluence scope and
> exclusions, media policy, Git identity, export mode, generated-at) and must:
> - validate every path is absolute and a plain file/directory chain, rejecting
>   symlinks and reparse points;
> - never reach the network - this is an offline boundary over preserved raw
>   evidence only;
> - emit sanitized output only (no credentials, URLs, page ids, titles, content,
>   paths, or full hashes) and keep the existing sanitized exit-code taxonomy;
> - refuse to publish a partial or non-deterministic snapshot.
>
> Confirm first whether `M10FullSnapshotExporter` accepts a Git handoff with a
> valid pinned identity but zero records. If it does, support a Confluence-only
> mode that pins a real repository/branch/commit and emits no Git rows. If it
> does not, stop and report that as a blocking contract question rather than
> weakening any validation.
>
> Adversarial negative pass is mandatory on the new CLI and composition boundary.
> Report exact commands and results.

**Exit:** `python -m knowledgenexus.foundation.cli.<new-cli> --help` works, and
an offline test publishes a full eight-stream snapshot plus manifest from
fixture raw evidence, twice, deterministically.

---

### W2 - Bind the subtree harness generation to the M10 request

**Prompt for codex:**

> The Gate A subtree harness (`cli/confluence_subtree_corpus.py`) captures raw
> pages and Draw.io bodies into a generation and writes
> `inventory-selection.json`, `processing-state.json`, and `drawio-state.json`.
> The W1 M10 CLI consumes a preserved generation and needs `ordered_page_ids`,
> `raw_generation_id`, and a media policy.
>
> Prove and enforce that these two agree. Specifically:
> - derive `M10SnapshotRequest.ordered_page_ids` from the harness
>   `inventory-selection.json` rather than from a hand-written list, preserving
>   its deterministic order and its run/generation and selection-identity binding;
> - confirm the raw layout written by `capture-pages` is exactly the layout
>   `ProcessConfluencePageSet` reads through `ConfluenceRawPageGenerationStore`,
>   and that the Draw.io attachment layout matches what the media stage reads;
> - fail closed on run id, generation id, fingerprint, or selection-identity
>   mismatch between harness state and the M10 request.
>
> Add an offline test that drives the harness end to end over a fake transport
> and then runs the W1 M10 CLI over the resulting generation, asserting the
> published snapshot's document and media counts match the harness packet.
> Report exact commands and results.

**Exit:** one offline test proves harness generation -> M10 snapshot with no
manual translation step.

---

### W3 - Confluence-only scope resolution — RESOLVED, no work needed

**verified.** A Confluence-only snapshot already works. Running the real
`M10FullSnapshotExporter` over `_handoffs()` with an all-empty `M10GitHandoff`
carrying a valid pinned identity published successfully: `status ==
"published"`, counts `{documents: 1, chunks: 1, relations: 1, acl: 1,
media_assets: 0, symbols: 0, sync_state: 1, tombstones: 0}`.

So the first snapshot may pin a real repository/branch/commit and emit zero
Git rows. No contract change and no operator decision is required. W1 carries
this as a settled input.

---

### W4 - Real-input gates (operator, main machine)

These require real credentials and the pinned tokenizer bundle, so they run on
the main machine, not the review machine.

Prerequisites the review machine does **not** have:

- `CONFLUENCE_BASE_URL`, `CONFLUENCE_PAT` (environment / secret store).
- The pinned BGE-M3 bundle: `tokenizer.json`, byte size `17098108`, sha256
  `21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08`, from
  `BAAI/bge-m3` commit `5617a9f61b028005a4858fdac845db406aefb181`. External
  directory only; implicit Hugging Face cache is forbidden
  (`contracts/foundation/embedding_profile.yaml`). This is why nine asset-backed
  tests report as not run on the review machine.
- Real `--space-key` and `--root-page-id` for Root 1.

Steps:

1. **Gate A acceptance (readiness doc section 5, A7).** Run Root 1 with the
   subtree harness: offline fault injection, small live tree, controlled stop
   after several batches, explicit resume of the same run, prove no refetch of
   committed windows/pages, deterministic repeat from the same raw generation,
   raw evidence unchanged by processing/export, sanitized logs.
2. **F4 media gate, minus OCR.** Text-first means Draw.io only. Do not enable
   `image_only_pdf`, `image`, or `chart_screenshot`. Convert processor results
   to `SanitizedMediaProcessorOutcome`/`SanitizedMediaProcessorRun` and evaluate
   with `EvaluateBoundedMediaCorpusAcceptance`. Note the existing media gate
   requires `real_capture_attested: true` and `transport: "production"`.
   **Open question for the operator:** the current gate evaluator may expect all
   five media kinds. If it does, a text-first Draw.io-only gate needs an
   explicit reviewed variant rather than a silently relaxed threshold.
3. **F5 first real full snapshot.** Run the W1 CLI twice over the same raw
   generation. Verify determinism, all eight JSONL files plus manifest, exact
   counts, relation/media/ACL/sync closure, atomic publication and no-clobber
   rollback. Retain only sanitized readback metadata.
4. **F6 second-sync delta.** Use the first snapshot as prior state; prove
   changed, deleted, moved-out-of-scope, and access-revoked entities; verify
   tombstone cascade to chunks, media, relations, and ACL; verify an ACL-only
   change re-emits ACL/chunks without inventing content tombstones.

**Exit:** Foundation complete for Confluence, text-first. Per the readiness
doc's completion language this is "Controlled full-text crawl ready" plus the
real M10 full and delta gates - it is **not** "Automatic recurring Confluence
crawl ready", which additionally needs readiness Gate B (scheduler, quarantine,
retention, observability).

## 4. Explicitly out of scope

- OCR and any image/PDF/audio/video processing (readiness doc section 8).
- `attachment_text` chunks (still blocked by D20).
- Readiness Gate B (unattended scheduling) and Gate C (concurrency, parallelism).
- Root 2 / HQ root - starts only after Root 1 is accepted.
- Embeddings, Qdrant, retrieval, PLM.

## 5. Guardrails for every work package

From `AGENTS.md`:

- Independent reviewers never edit files; a re-review runs in a new session.
- Every public/application boundary needs an adversarial negative pass:
  `object()`, `None`, wrong enum values, missing required fields, forbidden
  extra fields, impossible counters. Type annotations are not runtime validation.
- Never read, print, commit, or transmit `.env`, `.local_ai/evidence/`,
  `Tool_TRreport/`, raw runtime data, credentials, or unsanitized Confluence
  content.
- Implementers change only what the plan requires and report exact commands and
  results.
