# AI_Knowledge_Platform_v7_4_Update.md

| Field | Value |
|---|---|
| Status | Decision Log / Update Layer (normative where stated) |
| Date | 2026-07-08 |
| Based on | AI_Knowledge_Platform_v7_3_Update.md · v7_2_Update.md · Master_Spec_v7_1.md · CHUNKING_SPEC.md · schemas/ |
| Purpose | Capture the decisions agreed after the crawl-readiness / source-binding review: concrete POC source identities, dataset naming, Jira scope, the bge-m3 chunking direction, the advisory scope classifier, the media/chart/diagram crawl policy, and the media/chunk/ACL boundaries. This file layers on v7.3; it does not rewrite the master spec, and it never silently edits `schemas/` or `CHUNKING_SPEC.md` — where a decision touches those, the required patch is listed in Part B and must be applied deliberately before implementation/export. |

## Precedence (unchanged, extended)

Highest wins: `schemas/` → `CHUNKING_SPEC.md` → `Master_Spec_v7_1.md` → `v7_2_Update.md` → `v7_3_Update.md` → **this file (v7.4)**.

`Master_Spec_v7.md` remains the historical baseline (audit/diff only). Explainer docs remain non-normative (v7.2 D7).

## Changelog (v7.3 → v7.4)

| # | Area | Change |
|---|---|---|
| 1 | POC sources | Concrete identities bound: primary Confluence (SVMC/938880621, SPenSRV), primary Git (`spen-sdk`, branch `develop`), later HQ wiki (SPENSDK/271852384, disabled initially). D14. |
| 2 | Dataset naming | Stable `dataset_name: spen_knowledge_poc`, versioned snapshots per v7.2 D1. D15. |
| 3 | Jira | Regex-only confirmed; `allowed_project_keys` seeded with `SVMCSPEN`; **extract broad, filter by allowlist**. D16. |
| 4 | Embedding/chunking | POC runs bge-m3 (1024-dim); `chunker_version` **1.2.0 confirmed** for the bge-m3 generation; the initial `medium` budget is **provisional until benchmark** (`profile_status`, not the version, carries that); structure unchanged. D17. |
| 5 | Scope filtering | Advisory rule-based classifier ratified; page_relevance/media_policy split; pending_review defaults; provisional weights; 6 reclassify triggers; `moved_out_of_scope` on approved exclusion. D18. |
| 6 | Media/chart/diagram | Metadata-first crawl policy per asset type: draw.io parse-source-first, tables as source-of-truth, PDF text-first, chart images OCR-labels-only (no numeric fabrication). D19. |
| 7 | Media/chunk boundary | MVP emits **no** `attachment_text` chunks; media stays in `media_assets.jsonl`. D20. |
| 8 | Attachment ACL | MediaAsset inherits parent-document ACL; future media chunks must copy parent `acl_tags` deny-safely. D21. |
| 9 | Part 2/3 consumer | KnowledgeNexus named as the export consumer; Part 1 architecture unchanged; integration governed by a separate `Task2_Task3_Integration_Contract.md`. D22. |
| — | Contract patches | CHUNKING_SPEC §1 bge-m3 rewrite, `chunkerVersion` pre-release question, `spensdk`→`spen-sdk` doc-text fixes, historical tokenizer notes — enumerated in Part B, **not applied here**. |

---

# Part A — Normative decisions

## D14. POC source binding

**Primary Confluence wiki (enabled):**

```
confluence:
  base_url: "https://confluence-mx.sec.samsung.net"
  pat_env: "CONFLUENCE_PAT"
  sources:
    - source_id: "confluence_svmc_spensrv"
      product_area: "SPenSRV"
      space_key: "SVMC"
      include_roots:
        - page_id: "938880621"    # "1. S Pen SDK"
      exclude_subtrees: []        # filled after inventory review (D18)
```

Root page canonical URL `…/spaces/SVMC/pages/938880621/1.+S+Pen+SDK` (short `…/x/bS72Nw`).

**Primary Git repo (enabled, one branch — CHUNKING_SPEC identity constraint):**

```
git:
  sources:
    - repo_url: "https://github.sec.samsung.net/SPenSDK/spen-sdk"
      repo_name: "spen-sdk"       # canonical, hyphenated
      branch: "develop"
      acl_tag: "repo:spen-sdk"
```

`repo_name` is canonically **`spen-sdk`** (hyphenated), superseding the `spensdk` spelling used in v7–v7.3 example text. This is a data-value change wherever the name is materialized: `acl_tags` (`repo:spen-sdk`), `ChunkRecord.repo`, `CanonicalDocument.repo`, `SymbolRecord.symbol_id` prefix, and the git `document_stable_key` (`git:spen-sdk:{file_path}`, which participates in every code `chunk_id`). The `aclTag` schema pattern `repo:\S+` already accepts the hyphen — **no schema pattern change is needed**; only doc-text examples (Part B).

**One branch only.** The git `document_stable_key` is `git:{repo}:{file_path}` with no branch component; two branches of one repo in one dataset would collide on `chunk_id` (differing only in the provenance `branch` field). Multi-branch is therefore a design change, not a config toggle — deferred (Part D).

**Later / Phase 1.1 Confluence wiki (disabled initially):**

```
    - source_id: "confluence_spensdk_hq"
      product_area: "SPen HQ"
      space_key: "SPENSDK"
      enabled: false
      include_roots:
        - page_id: "271852384"    # "Tasks"
```

Root URL `…/spaces/SPENSDK/pages/271852384/Tasks` (short `…/x/YCM0E`). Run SPenSRV end-to-end before enabling HQ as a second source.

## D15. Dataset naming

- `dataset_name: spen_knowledge_poc` — stable across the corpus lifetime; chosen broad so future sources (HQ wiki, SamsungNotes, additional repos) join the **same unified corpus** (v7.2 D5), not a renamed one.
- `dataset_version` remains per-export snapshot; layout `data/exports/<dataset_name>/<dataset_version>/` with `LATEST.txt` pointer (v7.2 D1). Many versions are normal.
- **Unified-corpus obligation:** because all sources share one index, every source's deny-safe ACL mapping (v7.2 D4) is a blocking prerequisite *before* that source is exported — a single lax mapping contaminates the shared collection.

## D16. Jira

- POC stays regex-only; no Jira PAT required (Master §13). RelationRecords are `mentions_jira_key`, `resolution_status: unresolved_without_jira_api`.
- `allowed_project_keys` seeded with **`SVMCSPEN`** (evidence: Jira URL `…/SVMCSPEN-2318`). Not asserted to be exhaustive.
- **Extract broad, filter by allowlist (normative):** the extractor matches the full key pattern `[A-Z][A-Z0-9_]+-[0-9]+` and records *all* key-like strings in `quality_report.md`, but only allowlisted keys produce RelationRecords. This preserves signal for future Jira-PAT hydration without re-crawling, and lets the first inventory reveal other real keys (e.g. SPEN/NOTES/SDK) before they are added.
- **Implementation caution (see Part C):** the pattern false-positives on code constants (`ISO-8601`, `SHA-256`, macro tokens). Quality report must separate "allowlisted keys" from "key-like strings outside allowlist" so noise never enters real relations.

## D17. Embedding / chunking direction (bge-m3)

- POC embedding model is **`BAAI/bge-m3`** (open-weight, self-host), `vector_dim` **1024**. MiniLM is no longer the active POC target.
- Token counting MUST use the **bge-m3 tokenizer** (SentencePiece, XLM-RoBERTa-based) — not `tiktoken`, not MiniLM WordPiece. The `chunk_record.schema.json` `token_count` description is already model-agnostic (v7.3), so **no schema change** is needed for this.
- **`chunker_version` is `1.2.0` for bge-m3 (CONFIRMED, locked).** The loose "reset to 1.0.0" idea from review is dropped: `1.0.0` (cl100k) and `1.1.0` (MiniLM) are already occupied in the CHUNKING_SPEC §7 history, so reusing them would corrupt the audit trail. Monotonic continuation to `1.2.0` is the clean choice and matches the reservation already made in v7.3 D9.
- **Provisional/benchmarking status lives OUTSIDE `chunker_version`.** The schema pattern `^[0-9]+\.[0-9]+\.[0-9]+$` rejects pre-release suffixes (`1.2.0-rc.1` is invalid), so `chunker_version` stays strictly `1.2.0`. The provisional state is carried as `profile_status: provisional_until_benchmark` in **`embedding_profile.yaml`** (and surfaced in `quality_report.md`) — **not** written into `manifest.json`, whose schema is `additionalProperties: false` and would reject an unknown field. For machine-readable change detection, Part 2 keys on the **existing** required `manifest.config_hash` (a sha256 that already changes when the budget/config changes); a `config_hash` change invalidates the affected snapshot even when `chunker_version` is unchanged. Do not widen the version pattern (Part B item 2). If a machine-readable *profile identity* is later wanted in the manifest, that is an optional additive minor bump (Part B item 5), not required for MVP.
- **Record `schema_version` stays `1.0`** for all record types unless a schema-breaking or additive change is actually made. The bge-m3 move is a chunker/profile change, not a record-shape change, so it does not bump `schema_version`.
- **Provisional profile for the pipeline-test run (decision "A"):** `medium` from `embedding_profile.yaml` — `target_tokens 450 / hard_max_tokens 1000 / overlap_tokens 64`, carried under `chunker_version 1.2.0` + `profile_status: provisional_until_benchmark`. Rationale: mid-range on the benchmark sweep (least-regret restart distance); `target 450` and `overlap 64` (~14%) sit inside community consensus for bge-m3 on descriptive/technical prose; `hard_max 1000` is intentionally generous and is the one value to watch for dilution in Round 1. The benchmark winner keeps `1.2.0` and flips `profile_status` to `locked` — no version renumber.
- All chunk budget (`target/hard_max/overlap`, code-window params) MUST be config-driven (read from `embedding_profile.yaml`), so a post-benchmark budget change is a re-run, not a Task 2 code change (v7.3 D9).
- Changing the bge-m3 budget after any export triggers `config_invalidated` → fresh `full_snapshot` + full re-chunk/re-embed (Master §16.2).
- **Chunking structure is unchanged:** wiki by h1–h3 heading + breadcrumb first line; code by symbol chunks + fallback line-windows; `ChunkRecord.text` embedded **verbatim** by Part 2 (v7.2 D3) — Part 2 must not summarize/prepend/trim before embedding. Retrieval-time filtering/reranking is the place to reduce noise, never text mutation before embedding.

## D18. Scope filtering (advisory classifier)

- **Deterministic page-tree scope is the only exclusion authority:** `include_roots` and `exclude_subtrees` by `page_id`, human-approved. The classifier is **advisory** and MUST NEVER mutate `exclude_subtrees` automatically.
- **Two independent decisions, not one score:** `page_relevance` (does this page serve a work purpose?) and `media_policy` (are its attachments worth downloading?). A technical page heavy with screenshots must not be demoted on media grounds.
- **`pending_review` defaults:** page text is **included**; media is **metadata_only**. Uncertainty never drops data.
- **Scoring weights are provisional seeds only**, calibrated after the first real inventory. The exclude threshold is deliberately **conservative**: a false negative (losing a real design page) is more costly than a false positive (crawling one team-building page), so the classifier optimizes for low false-negative risk.
- **Reclassification triggers:** new page · missing prior decision · title/path/ancestor change · normalized-body `content_hash` mismatch · attachment inventory change · `classifier_version` change.
- **Scope-change tombstone:** a previously included page that later enters an approved `exclude_subtrees` is a scope change; in `delta` mode it MUST emit a tombstone with reason `moved_out_of_scope`, cascading to its chunks/media/relations/ACL (Master §16.2, §18.2). (No tombstone on the first `full_snapshot` — an excluded page simply does not appear.)
- Scope-decision artifacts are Part 1 **internal** (`data/work/scope_filter/scope_decisions.jsonl`, `data/reports/scope_review_report.csv`), never part of the export contract; Part 2 must not read them (v7.2 D1).
- **ACL is orthogonal to relevance:** a restricted page may still be relevant; if included, its records carry the correct deny-safe `acl_tags` (Master §14). Relevance filtering never overrides ACL.

## D19. Media / chart / diagram crawl policy

Metadata-first is mandatory (Master §11); download/process only when the parent page is relevant. Policy per asset type:

- **draw.io / diagrams.net (highest priority, no OCR):** from `body.storage`, detect `ac:structured-macro ac:name="drawio"`, resolve to the `.drawio/.xml` attachment, download if parent relevant, parse `mxfile`/`mxGraphModel`, and extract nodes / labels / edges / containers into `MediaAsset.extracted_text`. Create a `RelationRecord embeds_media`; the parent page keeps a `[diagram: {name}]` placeholder (Master §10.1). Diagram text comes from source, not from guessing at pixels.
- **Confluence tables / chart source data:** the table is the source of truth over any chart rendering. Preserve it as a Markdown table and chunk as `content_kind: table` — atomic if it fits, else row-group split repeating the header (CHUNKING_SPEC §4.6). Keep underlying data when a chart macro carries it.
- **PDF (text-first):** extract digital text and tables first (PyMuPDF/pdfplumber); OCR only scanned/image-only pages. Record a source locator (parent_page_id, attachment_id, filename, pdf_page_number, image_index, raw_uri) — see D20 for where it lives.
- **Images / screenshots / charts (OCR labels, never fabricate):** OCR title/axis/legend/data-labels into `extracted_text` with a confidence; do **not** reconstruct exact numeric series unless the underlying source data is available. Exact chart-data extraction is deferred to a Phase 1.5/2 vision pass with its own benchmark. When OCR is sparse or the chart is important, flag `manual_review_or_vision_needed` in `quality_report.md`. This directly serves the Master §20.1 risk "AI-generated docs become unverified truth" — the system states what it could not read rather than inventing it.
- **Parent page keeps placeholders**, not inlined OCR/diagram dumps: `[diagram: …]`, `[media: …]`, `[pdf_page: N]`. Extracted text lives in `media_assets.jsonl`, keeping pages from bloating while remaining discoverable through the media records.
- **Priority tiers:** P0 = page text, tables, `code` macro, draw.io macro/attachment. P1 = PDF text/table extraction, important-image OCR under relevant pages. P2 = OCR of all relevant images, chart-image detection, local-VLM summaries for selected diagrams. Deferred = video, exact numeric reconstruction from chart screenshots, full visual reasoning over every image.

## D20. Media / chunk boundary — no attachment_text chunks in MVP

- MVP emits **no** `attachment_text` chunks into `chunks.jsonl`. Media-extraction results stay in `media_assets.jsonl` only: `extracted_text`, `summary`, `confidence`, `processing_status`, `raw_uri`.
- Rationale: `chunkSourceType` supports `attachment_text`, but `content_kind` has **no** dedicated value for OCR/diagram-derived text; routing it through `prose` would mix derived/uncertain text with trusted original prose. Avoided.
- Detailed per-asset locators (`pdf_page_number`, `image_index`, etc.) are **not** MediaAsset top-level fields (`additionalProperties: false` would fail the export), and `media_asset.schema.json` exposes **no** free-form `metadata` object. They therefore live in an internal sidecar `data/work/media/media_extraction_details.jsonl`; the exported `MediaAsset` carries `raw_uri` plus inline markers such as `[pdf_page: 12]` in `extracted_text`.
- **Phase 1.5 path (deferred, Part D):** add `content_kind` value `extracted_media_text` (or `media_text`) as an additive minor schema bump, and optionally an exported `locators`/`metadata` field, if traceable media chunks are wanted in the contract.

## D21. Attachment ACL

- `MediaAsset` visibility **inherits** from `parent_document_id`; the parent document's `ACLRecord` is the authority in MVP.
- If attachment_text chunks are introduced later, those chunks MUST copy the parent page's `acl_tags` **deny-safely** (most-restrictive, per the Master §14.2 invariant). A diagram on a restricted page yields restricted extracted text.

## D22. Part 2/3 consumer (KnowledgeNexus) — pointer only

This is a pointer decision; it adds no Part 1 architecture. v7.4 remains a Part 1-internal decision log.

- **KnowledgeNexus is the designated Part 2/3 consumer** of Part 1's export (the indexer, hydrate store, Qdrant, retrieval API, and Gauss chat).
- **Part 1 architecture is unchanged.** Nothing about embedding, Qdrant, retrieval, or chat moves into Part 1. Part 1's deliverable stays the versioned export snapshot.
- **All integration details live in a separate document, `Task2_Task3_Integration_Contract.md`** — the export-snapshot consumer contract, the record→storage mapping, the KnowledgeNexus roadmap adaptation, and the hard constraints that make the handoff safe (verbatim embedding, deterministic point IDs, ACL enforcement, tombstone application, added storage for relations/acl/symbols/media/tombstones). That contract sits **below** `schemas/` in precedence (it consumes the schemas; it does not amend them).

---

# Part B — Required contract patches (NOT applied in this file)

These touch `schemas/` or `CHUNKING_SPEC.md` and must be applied deliberately before implementation/export, so the contract change is explicit and reviewable.

1. **CHUNKING_SPEC.md §1 — bge-m3 rewrite (blocking before chunk/export).** §1 is still written entirely around all-MiniLM-L6-v2 (WordPiece, 256-WP limit, 200/240/40). It must be rewritten for bge-m3 (SentencePiece tokenizer, 8192 context, the selected budget) when `chunker_version` 1.2.0 is locked. Until then §0.1 already flags §1 as the last locked baseline — but note that baseline is now historical, not the active POC target. Update §0.1's framing accordingly (v7.3 wrote it as "MiniLM still locked until benchmark"; the model choice is now bge-m3, so the wording should say the *budget* is pending benchmark, not the *model*).
2. **`chunkerVersion` pattern vs provisional labels.** `defs.schema.json` `chunkerVersion` is strict `^[0-9]+\.[0-9]+\.[0-9]+$` — it rejects pre-release suffixes like `1.2.0-rc.1`. Decision (D17): do **not** widen the pattern; keep `chunker_version` numeric and track provisional-vs-locked in `embedding_profile.yaml` (surfaced in `quality_report.md`). `manifest.json` continues to use `config_hash` for machine-readable change detection — do **not** write `profile_status`/`benchmark_profile_id` into `manifest.json` unless `manifest.schema.json` is explicitly extended later (item 5). If a semver pre-release scheme is ever preferred instead, that is a deliberate pattern-widening minor bump — not to be done silently.
3. **`spensdk` → `spen-sdk` in doc text (no schema pattern change).** The `aclTag` pattern `repo:\S+` already accepts the hyphen. Only example/description text needs correcting: `defs.schema.json` `aclTag` description, v7.2 D4 example (`repo:spensdk`), and any Master/CHUNKING example using `spensdk`. Data materialized during the run uses `spen-sdk` (D14).
4. **Historical tokenizer notes.** CHUNKING_SPEC §7 version history (`1.0.0` = cl100k, `1.1.0` = MiniLM) is a historical record and may stay, but should gain the `1.2.0` = bge-m3 line when locked. `chunk_record.schema.json` `token_count` is already model-agnostic (v7.3) — verify no other schema comment still names tiktoken/cl100k/MiniLM.
5. **(Optional, deferred) manifest profile-identity fields.** `manifest.schema.json` is `additionalProperties: false` and today carries `config_hash` + `chunker_version` but no profile identity. MVP does **not** need more: `config_hash` is sufficient for Part 2 to detect an invalidating change (D17). If a machine-readable profile identity in the manifest is later wanted (e.g. `embedding_model`, `vector_dim`, `embedding_profile_id`, `profile_status`), add them as **optional** properties — an additive minor bump, non-breaking. Not to be assumed by any consumer until actually added.

---

# Part C — Implementation notes (non-normative)

- **Wiki crawler = Python REST client**, not browser scraping. Suggested package layout under `part1-knowledge-foundation/`: `connectors/confluence/client.py`, `jobs/confluence_inventory_job.py`, `jobs/confluence_full_sync_job.py`, `processors/normalizer/`, `processors/media/`, `stores/local_raw_store.py`, `cli/sync_confluence.py`. Use `httpx`/`requests` with rate limiter, retry (respect `Retry-After`), and per-page/per-attachment checkpoints (Master §10, §18).
- **Job sequence:** Job 1 `confluence_inventory_job` (page tree + attachment metadata only → `inventory_report.csv`, `pages_inventory.jsonl`, `scope_decisions.jsonl`) → human reviews `exclude_subtrees` → Job 2 `confluence_full_sync_job` (`body.storage`, `version.number`, restrictions, attachment metadata → raw JSON) → normalize/chunk → Job 3 `media_extract_job v0` (draw.io/PDF parse, selective OCR).
- **Classifier tiering:** Job 1 runs the classifier at **tier-1 metadata only** (title/path/labels/attachment names/mime/counts) — enough to flag team-building/photo/travel and produce exclude candidates, without body fetch. **Tier-2 body-preview** classification for uncertain pages belongs to **Job 2** (it needs the same `body.storage` call full-sync makes). This keeps Job 1 free of body fetch, OCR, and embedding.
- **OCR = wrap existing tools, do not write an engine.** PDF text: PyMuPDF/pdfplumber first, OCR only for scanned/image-only. Image OCR: PaddleOCR (multilingual/technical) or Tesseract (simpler, mostly English); OpenCV/Pillow for preprocessing only (resize/grayscale/threshold/deskew). draw.io: parse XML directly, never OCR.
- **Benchmark reference (for Round 1 interpretation, not now):** community consensus for bge-m3 centers on ~512-token chunks with 10–20% overlap; the model author suggests ~512 is sufficient. No single chunk size wins every question group — design-why questions favor larger chunks, code/Jira identifier lookups favor smaller chunks + sparse/BM25 matching. This is why Round 2 (hybrid dense+sparse) is essential, not optional. Code stays on symbol boundaries; do not force it onto the prose budget. 37 anchors is statistically thin — report confidence intervals if profiles are close.

## Reusing the existing `tr_wiki_maker.py` helper (reference only)

An older internal script `tr_wiki_maker.py` publishes Markdown reports **to** Confluence. It is a **read-only reference** for the Confluence client, not a component to import wholesale.

- **Reuse as reference for:** Confluence base-URL handling; Bearer-PAT request headers; `requests` timeout pattern; internal proxy / TLS options; `argparse` CLI style; machine-readable JSON output style.
- **Do NOT reuse its write path:** no `create_confluence_page`, no `update_confluence_page`, no Markdown→storage publishing, and **no `POST`/`PUT` of any kind in the inventory job.** Part 1 crawlers are strictly read-only against Confluence (Master §10). The inventory/full-sync jobs issue `GET` only.

**Config migration (away from the script's plaintext token):**

- Do **not** carry over a plaintext `pat_token` from `confluence_config.json`. New config resolves the token from the environment:

```yaml
confluence:
  base_url: "https://confluence-mx.sec.samsung.net"
  pat_env: "CONFLUENCE_PAT"
  verify_ssl: false          # internal CA / on-prem DC
  proxies:
    https: null              # honor internal proxy / no-proxy as needed
```

- The inventory job reads `os.environ["CONFLUENCE_PAT"]` and **fails safely (clear error, non-zero exit) if it is missing** — it never proceeds unauthenticated or falls back to a file token.

**Token security (mandatory):**

- Never log the token. Never write it to a checkpoint, report, or any output JSONL.
- Redact the `Authorization` header in any debug/trace logging.
- The token exists only in process memory, sourced from the environment — not in config files, not in the raw store, not in exports.

---

# Part D — Deferred / post-MVP

- `attachment_text` chunks + `content_kind` enum addition (`extracted_media_text`) — Phase 1.5, additive minor bump (D20).
- HQ wiki (SPENSDK/271852384) — Phase 1.1, after SPenSRV runs end-to-end (D14).
- Multi-branch of one repo — needs branch-aware document/chunk identity or per-branch datasets; not a config toggle (D14).
- Exact numeric chart-data reconstruction / local-VLM visual reasoning — Phase 1.5/2 with its own benchmark (D19).
- Jira-PAT hydration of extracted keys into full issue records — when PAT is granted (Master §13); broad extraction (D16) preserves the keys until then.
- `module_map.yaml` / `module_summary` (v7.2 D6) — Phase 1.5.
- Git history / commit / PR ingestion and its relation types (v7.3 D11) — post-MVP.

---

# Open questions

Resolved in v7.4: primary source identities, canonical repo name, dataset name, initial Jira key, bge-m3 direction + provisional profile, **`chunker_version` 1.2.0 (confirmed)**, classifier design, media/chart policy, media/chunk/ACL boundaries.

Still open:

- `data_root` path + `max_disk_gb` — must be fixed **before** any full media crawl (still `<TBD>`).
- Real `CONFLUENCE_PAT` / `GITHUB_ENTERPRISE_TOKEN` values — at code time; local-clone git scan may not need the token day one.
- `exclude_subtrees` real page IDs — after Job 1 inventory.
- Winning bge-m3 budget + final `1.2.0` numbers — after Round 1; Round 2 decides hybrid value.
- Additional Jira project keys (SPEN/NOTES/SDK?) — after inventory reveals them.
- Benchmark anchors: fill the 37-item template with real `page_id`/`symbol`/`file_path`/`jira_key` from the crawled corpus — owner + timing.
- Task 3 retrieval design document (v7.3 D13) — owner + timing.
- Query-time ACL resolver for `repo:spen-sdk` (GitHub Enterprise teams) — blocking for multi-user, not for the single-user PAT POC.
- Task 2 output-validation owner (carried from Master §20.3).
