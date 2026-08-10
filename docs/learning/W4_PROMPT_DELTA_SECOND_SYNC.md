# W4 implementer prompt — operator-runnable second-sync delta

Hand this file to a codex implementer as one task. It is W4 of
`docs/learning/CONFLUENCE_FOUNDATION_CLOSEOUT_PLAN.md`. **W1 and W2 must be
complete first.**

---

## Why this exists

The Foundation Definition of Done requires more than a full snapshot: it
requires *"a second-sync delta path for changed, deleted, moved-out-of-scope,
and access-revoked entities."* W1 covers `export_mode="full_snapshot"` only.
Without W4, Foundation is not closed.

## Verified starting state

Confirmed by reading the code at `764efa3`. More is already built than the
full-snapshot path had before W1.

**Already exists and is production-ready:**

1. `M10DeltaSnapshotExporter` (in
   `infrastructure/exporters/m10_snapshot_exporter.py`) — fully wired
   internally. It constructs its own `M10DeltaOrchestrator`. Signature:
   `M10DeltaSnapshotExporter(prior_snapshot_reader=, schema_validator=None,
   delta_inventory=(), **kwargs)` where `kwargs` carries `confluence_adapter`
   and `git_adapter` exactly as the full exporter does. It raises if you pass
   `delta_orchestrator` yourself.

2. `PublishedSnapshotReader(dataset_root=, validator=)` (in
   `infrastructure/exporters/delta_snapshot_reader.py`) — a concrete,
   production-ready `prior_snapshot_reader`. It validates the dataset version
   pattern, rejects reparse points, and follows delta→base chains up to 32 deep.

3. `DeltaInventoryState` already enumerates exactly what the Definition of Done
   requires, plus one more: `PRESENT`, `SOURCE_DELETED`, `ACCESS_REVOKED`,
   `MOVED_OUT_OF_SCOPE`, `CONFIG_INVALIDATED`.

4. `DeltaInventoryEntry(document_id, state, source_version_last_seen=None)`.

5. `ProjectTombstones` and `PropagateDelta` handle the cascade.

**Guards the orchestrator already enforces** — do not duplicate or weaken them:

- `request.export_mode == "delta"` and `projection.export_mode == "delta"`;
- `request.base_dataset_version is not None`;
- prior manifest `dataset_version` equals `request.base_dataset_version`;
- prior manifest `chunker_version` equals the current projection's — an older
  snapshot is never diffed as if it used the same chunk semantics;
- prior manifest `config_hash` is a string.

`M10SnapshotRequest` itself enforces that `delta` requires
`base_dataset_version`, and that `full_snapshot` must **not** declare one.

**What is missing — this is the task:**

- `M10DeltaSnapshotExporter` has **no production wiring anywhere** — the same
  condition the full exporter was in before W1.
- Nothing builds `delta_inventory`. That classification is the real work.

## What to build

### A. Delta mode on the operator CLI

Extend the W1 CLI (or add a sibling) to accept `--export-mode delta` plus
`--base-dataset-version`, construct `PublishedSnapshotReader` over the dataset
root, and run `M10DeltaSnapshotExporter` instead of the full exporter.

Reuse W1's argument validation, path safety, sanitized output, and exit-code
taxonomy unchanged. Refuse `--base-dataset-version` in full-snapshot mode and
require it in delta mode — mirror the model's own rule rather than inventing a
second one.

### B. Build `delta_inventory` by classifying against the prior snapshot

For each document in the prior accepted snapshot, classify its current state.
This is the genuinely new logic and the part most likely to be got wrong.

The hard part is that `SOURCE_DELETED`, `MOVED_OUT_OF_SCOPE`, and
`ACCESS_REVOKED` are **not** distinguishable from "absent from the current
inventory" alone. All three look identical if you only diff page-id sets.
Distinguishing them requires evidence:

- **`MOVED_OUT_OF_SCOPE`** — the page still exists but is no longer under the
  configured include root, or now matches an exclusion. The harness's scope
  configuration and each occurrence's `ancestor_page_ids` carry this.
- **`ACCESS_REVOKED`** — the page is no longer readable. This is a restriction
  or authorization signal, not an absence. The M7 raw restriction/orphan
  inspection seams are the place to look.
- **`SOURCE_DELETED`** — genuinely gone from the source.
- **`CONFIG_INVALIDATED`** — the chunker or config identity changed. Note the
  orchestrator already **rejects** a `chunker_version` mismatch outright, so
  work out what this state is actually for before emitting it.

**Do not collapse these into a single state to make a test pass, and do not
guess a classification you cannot evidence.** If the current durable state
genuinely cannot distinguish two of them, say so plainly in your report and
propose what evidence would be needed — that is a far better outcome than a
delta that silently mislabels a revoked page as deleted.

An ACL-only change must re-emit affected ACL and chunk records **without**
inventing content tombstones.

### C. Tests

- **The forcing test.** Publish a full snapshot, then publish a delta bound to
  it, offline, end to end. Assert the delta's manifest carries
  `export_mode: "delta"` and the correct `base_dataset_version`.
- One test per required case: **changed**, **deleted**, **moved out of scope**,
  **access revoked** — each asserting the resulting stream contents and the
  tombstone cascade into chunks, media, relations, and ACL.
- An **ACL-only change** test asserting ACL and chunks are re-emitted and no
  content tombstone is created.
- A determinism test: the same delta published twice is byte-identical.
- Negative tests: `base_dataset_version` missing in delta mode; present in full
  mode; pointing at a nonexistent version; pointing at a snapshot with a
  different `chunker_version`. Each must fail closed with the right sanitized
  category.
- Adversarial negative pass per `AGENTS.md` on every new public boundary.

## Scope boundaries

- **In scope: delta correctness.** A second full crawl compared against the
  prior snapshot satisfies the Definition of Done.
- **Out of scope: the B1 efficiency optimization** — skipping body fetch and
  reprocessing for unchanged pages. That is readiness-doc Gate B. Do not build
  it here; it will only obscure whether the delta itself is correct.
- Out of scope: scheduler, quarantine policy, retention, observability.
- Do not weaken, bypass, or special-case existing validation. If a contract
  genuinely blocks the task, **stop and report it**.
- Do not reimplement diffing, tombstone, propagation, or publication logic —
  `M10DeltaOrchestrator`, `PropagateDelta`, and `ProjectTombstones` own it.

## Constraints

- Do not run live Confluence requests. Do not read, print, or commit `.env`,
  `.local_ai/evidence/`, `Tool_TRreport/`, raw runtime data, credentials, or
  unsanitized Confluence content.
- The pinned BGE-M3 tokenizer bundle is **not available on this machine**.
  Asset-backed tests `pytest.fail` without `--tokenizer-assets-dir`; report
  them as **not run**, never as failures, and never satisfy them with an
  implicit Hugging Face cache. Inject a tokenizer double in your own tests.
- Text-first. No OCR, no PDF/image/audio/video, no `attachment_text` chunks.

## Environment

```
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Run and report exact commands and results for:

```
python -m pytest tests/foundation tests/shared tests/architecture -q
```

Take your starting baseline from the W2 commit and report any new failure as
yours. For reference, at `764efa3` (before W1) it was **3264 passed, 40
skipped, 9 errors** in `tests/foundation` (all nine asset-backed BGE-M3), plus
**117 passed** in `tests/shared tests/architecture`.

## Definition of done

An offline test publishes a full snapshot, then a delta bound to it, proving
changed, deleted, moved-out-of-scope, and access-revoked documents with correct
tombstone cascade — and an ACL-only change that re-emits ACL/chunks without
inventing content tombstones.
