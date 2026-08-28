# Live Sync — incremental crawl (Approach B1) implementation plan

Status: **implemented** on `live-sync-incremental` and unit-tested (fetcher,
CLI loader, export flag threading, `execute_sync` wiring; full suite adds no new
failures). Needs validation on a real multi-page sync — watch `reused_pages`.

Goal: on `sync-apply`, do **not** re-fetch page bodies over the network for
pages that did not change. Fetch live only the changed/new pages; serve the
unchanged pages' bodies from the baseline workspace's raw store.

This is the safe variant identified in `LIVE_SYNC_APPROACH_B_SURVEY.md`: it
changes **only the page fetcher**, never the checkpoint / capture / export
contracts. Every phase still runs over the full inventory and produces the same
full packet; the unchanged pages are simply captured from disk instead of the
network.

## Why this is safe

- `ConfluencePageFetchPort` is a one-method protocol: `fetch_page_raw(page_id)
  -> bytes` (the raw Confluence API response). A decorator that returns the
  baseline body for unchanged pages, and delegates to the live adapter for the
  rest, is a drop-in.
- For an unchanged page, `current source_version == baseline source_version`, so
  the baseline raw body **is** the current body byte-for-byte-equivalent (same
  version = same content). `FetchAndStoreConfluenceRawPageGeneration` re-derives
  the version from the body and stores it under the new generation exactly as if
  it had been fetched live. Every checkpoint / acknowledge / export invariant
  holds.
- Unchanged pages are **not indexed** anyway — `execute_sync` already restricts
  indexing to changed/new documents via `include_document_ids`. So even the
  chunks produced from the reused body are discarded; the reuse only has to be
  good enough to let the pipeline complete.
- If a baseline raw page is missing (pruned) or its version does not match, the
  decorator falls back to a live fetch for that page. Safe degradation.

## What it does NOT save

- Normalize + chunk (CPU) still runs for unchanged pages. Skipping that would
  require narrowing the selection, which fights the checkpoint "complete
  generation over the full inventory" model — out of scope, high risk.
- The saving is the **network round-trip per unchanged page**, which is the
  dominant cost of a large-root sync over a corporate network.

## Components

1. **`BaselineAwarePageFetcher`** (foundation/infrastructure/confluence): a
   `ConfluencePageFetchPort` decorator. Holds `inner` and
   `baseline_bodies: dict[page_id -> bytes]` (unchanged pages only). Returns the
   stored body when present, else `inner.fetch_page_raw`. Counts reuses for
   telemetry.

2. **`capture-pages` phase** (`confluence_subtree_corpus.py`): three new,
   optional args — `--reuse-baseline-raw-root`, `--reuse-baseline-run-id`,
   `--reuse-unchanged-path` (a JSON file: `[{page_id, source_version}]`). When
   all present, load each unchanged page's baseline raw body (only if the
   passed version matches the current selection's `expected_source_version` and
   the baseline raw page loads), build `baseline_bodies`, and wrap the fetcher.
   Absent → unchanged behaviour.

3. **`run()`** (`export_confluence_url_text_snapshot.py`): optional
   `reuse_baseline` argument `{raw_root, run_id, versions: {page_id: version}}`.
   When present, write the versions to a workspace file and append the three
   flags to the `capture-pages` invocation. Absent → unchanged.

4. **Ingestor** (`ingest_confluence_subtree_from_url.py`): `_publish_packet`
   gains an optional `reuse_baseline`. `execute_sync` derives it from the
   baseline workspace — raw root = `baseline_workspace/.raw`, run_id from the
   baseline `LATEST.txt` version name, versions from `read_packet_pages` — and
   passes the unchanged set. A first sync (no baseline) passes nothing.

5. **Telemetry**: `execute_sync` reports `reused_pages` / `fetched_pages` in job
   stats so the UI/logs show how much network was avoided.

## Test plan

- `BaselineAwarePageFetcher`: reuse hit returns baseline body without touching
  inner; miss and version-mismatch delegate to inner; reuse count correct.
- Capture phase (offline, fake transport + fake baseline raw store): unchanged
  pages are captured with **zero** live fetches; changed pages fetched live.
- `execute_sync` (existing offline harness): with a baseline, unchanged pages
  are reused and not fetched; changed/new pages fetched; index + tombstone
  results unchanged from Approach A; `reused_pages` reported.
- Regression: full ingest (`reuse_baseline=None`) path byte-identical to before.

## Fallback

Approach A stays intact: `execute_sync` with no baseline, or with reuse
disabled, behaves exactly as today. The reuse is a pure optimization layered on
top, guarded by the baseline being present.
