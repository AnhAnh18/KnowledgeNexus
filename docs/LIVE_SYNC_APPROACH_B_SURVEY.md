# Live Sync — Approach B (incremental crawl) survey

Status: **survey only, no code.** Approach A (full re-crawl, embed only the
changed pages) is shipped and is the safe default. This documents whether the
crawl itself can be made incremental, what it would cost, and the risk.

## 1. What Approach A does today, and where the cost is

A `sync-apply` re-runs the proven subtree pipeline and skips embedding for
unchanged pages:

| Phase | Scope in A | Cost |
|---|---|---|
| Inventory (list pages + `source_version`) | whole tree | network, metadata only (search-API windows, not page bodies) |
| Capture (fetch page **bodies**) | whole tree | **network — the dominant crawl cost** |
| Normalize + chunk | whole tree | CPU |
| Embed (dense+sparse vectors) | **changed/new only** ✅ | CPU — the slowest single phase (BGE-M3 on CPU) |
| Store + tombstone | changed/new/deleted only ✅ | I/O |

A already removes the slowest phase (embedding) for unchanged pages. What it
does **not** remove is the body **capture** of every page. On a 5k-page root
that changes rarely, every sync still fetches 5k page bodies.

## 2. The blocker

`CaptureConfluenceSubtreePages.run` (foundation/application/use_cases) binds a
capture run to the **entire inventory it streamed**. Each page is fetched only
when its checkpoint replay decision is `MISSING`; an already-captured page in
the same generation is `REPLAYED` and skipped. But every `sync-apply` starts a
**new `run_id`/generation**, so in that fresh generation *every* page is
`MISSING` → every body is re-fetched. Narrowing the streamed selection is
rejected outright (`selection binding mismatch`). So the crawl cannot simply be
told "only fetch the changed pages."

## 3. `CaptureDeltaInventory` does NOT solve this

The delta building blocks (`CaptureDeltaInventory`, `ClassifyDeltaInventory`,
`capture-delta-inventory` phase) exist, but they are a **deletion classifier**,
not an incremental-fetch engine:

- They probe only `missing = prior_documents − current_selection` — i.e. pages
  that **disappeared** from the selection.
- Each is classified `SOURCE_DELETED` / `ACCESS_REVOKED` / `MOVED_OUT_OF_SCOPE`.
- They never re-fetch the body of a page that is present-but-**changed**.

So delta inventory could make the **tombstone step more accurate** (today A
treats any missing page as deleted; delta would distinguish a truly deleted
page from one that only lost access or moved out of scope), but it does nothing
for crawl speed of changed pages.

There is also a **format mismatch**: `CaptureDeltaInventory` reads its baseline
through `PublishedSnapshotReader` in the **dataset-snapshot** format
(`streams["documents"]`, `document_id = "confluence:page:<id>"`, `source_version`)
under a `dataset_root`. The live-sync path publishes the **text-demo packet**
format (`documents.jsonl` with `page_id` + `source_version`). Using delta
inventory at all requires publishing a dataset-format snapshot or writing an
adapter.

## 4. Three ways to make the crawl incremental

### B1 — Reuse baseline raw pages into the new generation (highest fidelity)

Before capture, copy the baseline workspace's raw page artifacts for the
**unchanged** pages into the new generation's raw store, re-keyed to the new
`run_id`, so `capture-pages` replays them and only fetches the changed/new
pages. The rest of the subtree pipeline (process → drawio → export) runs
unchanged, so drawio/media/cross-page relations stay correct.

- **Effort:** medium-high.
- **Risk:** high. The M7 raw-generation contract deliberately binds each raw
  page to a `(run_id, generation_id)` and validates it through the checkpoint
  replay + orphan-inspection seam — a page is not "present" just because a file
  exists; the checkpoint ledger must acknowledge it. Re-keying artifacts across
  generations touches contracts the roadmap marks "approved, independently
  reviewed PASS," so it needs a Foundation-owner review, not just an Indexing
  change.
- **Fidelity:** high — identical to a full ingest for the pages it does fetch.

### B2 — Indexing-layer packet merge (most self-contained, fidelity risk)

Inventory (cheap) → diff → single-page fetch+process+chunk for changed/new only
→ reuse the baseline packet's chunks for unchanged pages → merge → index
changed/new, tombstone deleted. This is closest to what an operator imagines
("only update the changed part").

- **Effort:** medium, mostly in Indexing.
- **Risk:** medium-high on **fidelity**. The single-page path does not reproduce
  the subtree export's cross-page relations, media closure, or drawio handling
  identically. A changed page whose diagram/relations differ under single-page
  processing would index differently than a full ingest would — a correctness
  gap in a retrieval index.

### B3 — Delta inventory for accurate tombstones only (not crawl speed)

Wire `CaptureDeltaInventory` in to classify disappeared pages precisely.

- **Effort:** medium (the §3 format adapter).
- **Value:** improves deletion accuracy; **does not** speed up the crawl.
- Does not address the operator's actual concern.

## 5. Recommendation

1. **Measure first.** On the real 5k root under Approach A (plus the main
   machine's `#151 High-Speed Live Operations`, which may already narrow or
   speed the capture — confirm what #151 changed before building anything), time
   the capture phase specifically. If capture is not actually the bottleneck,
   B is not worth its risk.
2. If capture is the bottleneck, pursue **B1** — it is the only option that cuts
   the dominant cost while keeping full packet fidelity — as a **scoped
   Foundation milestone with owner review**, not an Indexing-only change.
3. Treat **B3** (accurate tombstones via delta inventory) as a **separate,
   smaller** improvement, independent of crawl speed, if deletion precision
   (deleted vs access-revoked vs moved) turns out to matter for the demo.
4. Do **not** ship **B2**: lower fidelity than a full ingest is the wrong
   trade-off for a correctness-sensitive index.

## 6. Files read for this survey

- `foundation/application/use_cases/capture_confluence_subtree_pages.py` — the
  full-inventory capture binding and the `MISSING`→fetch / `REPLAYED`→skip logic.
- `foundation/application/use_cases/capture_delta_inventory.py` — probes only
  `prior − current`; deletion classifier, not incremental fetch.
- `foundation/application/use_cases/classify_delta_inventory.py` — dispositions
  `SOURCE_DELETED` / `ACCESS_REVOKED` / `MOVED_OUT_OF_SCOPE`.
- `foundation/infrastructure/exporters/delta_snapshot_reader.py` and the
  `capture-delta-inventory` phase in `foundation/cli/confluence_subtree_corpus.py`
  — the dataset-snapshot baseline format the delta path expects.
- `indexing/application/use_cases/ingest_confluence_subtree_from_url.py` and
  `preview_confluence_sync.py` — where Approach A currently skips embedding.
