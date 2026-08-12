# Confluence Crawl Automation Readiness

## 1. Purpose

This note records the remaining work before KnowledgeNexus can run a bounded,
unattended Confluence crawl. It is a planning and review aid, not a replacement
for the active Foundation contracts.

The current delivery priority is **text first**. OCR and broad binary-media
processing are deliberately deferred until the text pipeline is reliable at
the target scale.

No repository-specific commit SHA is authoritative here. Progress should be
reported by milestone and acceptance gate so the note remains valid across the
source-review and main-machine repositories.

## 2. Locked near-term scope

### Included

- One configured Confluence Data Center deployment and one bounded root tree.
- Approximately 5,000 pages, with a hard ceiling no greater than the active
  approved reliability profile.
- Page storage XHTML and its normalized text representation.
- Headings, paragraphs, lists, tables, code blocks, links, supported macros,
  Jira-key relations, and existing ACL/default-deny behavior.
- Draw.io XML text and graph labels when they can be extracted deterministically
  from the original structured attachment. This is structured parsing, not OCR.
- Generation-scoped immutable raw evidence, deterministic processing, and an
  indexing packet containing documents and chunks. Media assets may be carried
  in a separate stream when the active contract requires them.

### Deferred

- OCR for screenshots, scanned PDFs, images, and image-only diagrams.
- General PDF/document extraction.
- Audio/video transcription and voice processing.
- Broad attachment download unrelated to an explicitly selected supported
  structured-text format.
- Semantic understanding of diagram geometry beyond deterministic labels,
  nodes, edges, and containers already supported by the Draw.io processor.
- Distributed crawling and unrestricted HTTP concurrency.

Deferred does not mean removed from the product roadmap. OCR and broader media
processing remain planned as a lower-priority track after the first two text
roots are operating reliably. Section 8 defines the staged OCR track.

## 3. Root rollout policy

The initial production rollout is deliberately staged by root rather than
combining every available root into the first operational run.

### Root 1 — initial controlled root

- Use the current approved root as the first approximately 5,000-page text
  corpus.
- Complete the full Gate A acceptance, including intentional stop/resume and
  indexing-packet verification.
- Use this run to measure response size, request latency, retry rate, raw disk
  growth, page failure rate, chunk volume, and Draw.io prevalence.
- Do not call the general crawler production-ready merely because a small
  mini-corpus passed.

### Root 2 — HQ root

- Start only after Root 1 has an accepted full-text result and the operational
  budgets have been reviewed against its measurements.
- Use a distinct crawl run, raw generation, scope fingerprint, checkpoint
  state, evidence summary, and output packet.
- Do not reuse Root 1 progress or raw evidence merely because both roots use
  the same Confluence deployment.
- If the roots overlap, use the approved overlapping-root compatibility and
  deduplication rules. Do not silently select one occurrence or use
  last-write-wins.
- Run the same controlled stop/resume and output validation gates before adding
  the HQ root to unattended scheduling.

M7 supports multiple include roots, but separate first-run acceptance reduces
the failure blast radius and makes capacity measurements attributable to one
scope. A later scheduler may manage both roots while retaining independent run
identity and durable progress for each configured scope.

## 4. Existing foundations

The repository already contains important pieces that should be composed, not
reimplemented:

- M7 durable inventory checkpoints per root/window, explicit and unique
  incomplete-run resume, single-writer locking, request reservations, bounded
  retry, controlled stop, and generation-scoped raw stores.
- M7 raw-page and restriction progress records plus orphan inspection/replay.
- Batch identities, leases, deterministic partitioning, and committed-batch
  re-entry.
- M8 page normalization, structural parsing, deterministic chunking, and the
  mini-corpus acceptance path.
- M9 tombstone and delta-propagation rules.
- M10 full/delta snapshot composition and publication boundaries.

These foundations do **not** by themselves constitute one production-ready,
unattended full-tree operator command.

## 5. Gate A — controlled full-text crawl

The following items block the first controlled 5,000-page crawl.

### A1. Full-corpus operator composition

Provide one thin operator harness that composes the existing production
components without duplicating HTTP, CQL, pagination, normalization, chunking,
ACL, relation, or export logic.

Prefer separately resumable phases:

```text
inventory
-> capture page bodies
-> capture selected Draw.io bodies
-> normalize/chunk/project
-> export indexing packet
```

A phase failure must not invalidate an already completed earlier phase.

### A2. Page-level resume inside bounded batches

Use batches of 100 as bounded work units, while persisting progress at page
granularity:

```text
fetch one page
-> atomically publish immutable raw bytes
-> durably acknowledge raw_page_progress
-> continue
```

After a crash, already valid pages must be replayed or skipped. Only the page
whose response/publication was not durably completed may need to be fetched
again. A committed batch must never be fetched again.

The acceptance suite must force a crash in the middle of a batch and prove
that resume does not refetch its already committed pages.

### A3. Inventory-to-page binding

- Bind every selected page to the same crawl run/generation and inventory
  fingerprint.
- Preserve the observed `source_version` and validate it during page
  processing.
- Reject duplicate, missing, out-of-scope, or conflicting page identities.
- Stream inventory rows in bounded groups; do not materialize the complete
  corpus unnecessarily.

### A4. Reliability-profile budgets

For the initial target, use an approved profile whose finite limits cover the
expected 5,000 pages with explicit headroom:

- unique pages;
- inventory windows;
- total HTTP attempts, including retry reservations;
- per-response bytes;
- total raw bytes and artifact count;
- minimum free-disk reserve;
- attachment/Draw.io counts and bytes;
- controlled-stop thresholds.

Do not override locked limits ad hoc from a CLI.

### A5. Draw.io-only attachment selection

- Fetch attachment metadata only through the approved pagination path.
- Download only an exact, version-bound Draw.io/XML candidate referenced by the
  page or approved observation.
- Do not download unrelated images, PDFs, audio, video, or generic binary
  attachments.
- Missing or malformed Draw.io must produce a typed media failure while
  preserving the page's normalized text and placeholder. It must not discard
  the rest of the corpus.

### A6. Output handoff

Produce a deterministic, schema-validated packet suitable for the indexing
team. At minimum:

```text
documents.jsonl
chunks.jsonl
packet_summary.json
```

If structured Draw.io text is not emitted as page chunks under the active
contract, carry it separately:

```text
media_assets.jsonl
```

Do not silently inline an entire diagram dump into the parent-page chunks.
The indexing consumer must explicitly agree how `media_assets.jsonl` is
ingested before Draw.io text is claimed searchable.

### A7. Controlled scale acceptance

Before a full 5,000-page attempt, prove:

1. offline fault injection;
2. a small live tree;
3. controlled stop after several inventory/page batches;
4. explicit resume of the same run;
5. no refetch of committed windows/pages;
6. deterministic repeat processing from the same raw generation;
7. raw evidence unchanged by processing/export;
8. output schema/count/hash consistency;
9. aggregate-only logs with no credential, URL, page ID, title, content, path,
   or full-hash leakage;
10. no automatic retry of an operator run after an unknown failure.

## 6. Gate B — unattended recurring crawl

The following items may follow the first controlled full crawl, but they block
calling the system an automatic recurring crawler.

### B1. Incremental live collection

The repository has delta/tombstone projection, but still needs an operator
path that efficiently constructs the next live generation:

- compare inventory `source_version`/`updated_at` with the prior accepted run;
- skip body fetch and processing for unchanged pages;
- fetch and reprocess new or changed pages;
- detect source deletion and movement out of scope;
- detect ACL-only changes without unnecessarily changing content IDs;
- pass explicit inventory states into the existing delta/tombstone stage;
- publish a `delta` snapshot bound to the accepted base dataset version.

Until this path exists, a second run may still need to inventory the full tree
and may fetch more content than necessary.

### B2. Scheduler and run ownership

- Define how a scheduled run starts, resumes, pauses, or is abandoned.
- Never select the newest incomplete run implicitly.
- Guarantee one active writer for one crawl scope.
- Define maintenance-window and controlled-stop behavior.
- Make credentials environment/secret-store supplied and process-scoped.
- Ensure operator configuration cannot weaken contract-locked safety limits.

### B3. Failure and quarantine policy

Define corpus-level disposition for an individual page or Draw.io failure:

- failures that stop the entire run;
- failures that quarantine one item but allow bounded continuation;
- maximum failure count/rate;
- deterministic retry eligibility;
- how a later successful run clears a quarantine;
- how incomplete/partial output is prevented from becoming `LATEST`.

### B4. Retention and disk lifecycle

- Retain generations referenced by an accepted snapshot or resume checkpoint.
- Pin cross-run evidence that is reused.
- Define explicit operator-approved cleanup; never delete generations
  automatically merely because a run failed.
- Forecast and monitor raw, checkpoint, packet, and temporary-file growth.
- Stop before violating the configured free-disk reserve.

### B5. Operational observability

Expose aggregate, non-sensitive metrics:

- pages discovered/fetched/replayed/skipped/failed;
- committed inventory windows and page batches;
- requests, retries, retry delay, and rate-limit outcomes;
- raw bytes/artifacts and free-disk margin;
- elapsed time and throughput;
- Draw.io candidates/successes/failures;
- generated documents/chunks/media rows;
- run state and sanitized failure category.

Metrics must be derived from durable state where practical rather than only
from process-local counters.

## 7. Gate C — optimization after correctness

### C1. Parallel offline processing first

Normalize, parse, chunk, validate, and process Draw.io in a small bounded worker
pool after raw evidence is durable. Preserve deterministic output ordering and
single-writer publication.

### C2. HTTP concurrency only by explicit contract migration

M7-v1 intentionally uses sequential HTTP requests. Adding concurrent fetches
requires a reviewed profile and tests for:

- a global rate limiter shared by all workers;
- global durable request-budget reservations;
- `Retry-After` coordination;
- per-batch lease fencing and stale-worker rejection;
- no-clobber raw publication;
- serialized checkpoint transactions;
- deterministic output independent of completion order;
- crash and partial-worker failure recovery;
- an administrator-approved aggregate request rate.

Do not use multiple workers to bypass the current three-second global pacing
policy. Measure a successful single-HTTP-worker run before increasing source
load.

## 8. Low-priority OCR and extended-media track

OCR is retained as an explicit later track so the current text-first delivery
does not create an undocumented product gap.

### OCR-1. Contract and evidence profile

- Define supported image and PDF MIME types and explicit exclusions.
- Pin OCR engine/model identity, language packs, runtime versions, and offline
  asset provenance.
- Define per-file bytes, page count, pixel dimensions, processing time, total
  corpus budget, and decompression-bomb defenses.
- Define confidence, empty-result, partial-page, malformed-file, encrypted-PDF,
  and unsupported-format semantics.
- Keep OCR output provenance traceable to the parent page, attachment ID,
  attachment version, page number, and bounding region where available.

### OCR-2. Safe binary capture

- Add exact metadata-to-body identity binding and immutable raw storage for
  allowlisted image/PDF attachments.
- Preserve no-clobber publication, request budgets, disk reserve, orphan
  replay, and resume behavior.
- Never download every attachment merely because OCR exists.

### OCR-3. Deterministic extraction and projection

- Normalize OCR text without silently inventing or correcting source meaning.
- Carry confidence and extraction warnings separately from searchable text.
- Define whether extracted text becomes `attachment_text` chunks or a media
  stream consumed explicitly by Indexing.
- Preserve stable IDs and update/tombstone behavior when an attachment version
  changes or disappears.

### OCR-4. Retrieval and quality acceptance

- Use a sanitized representative corpus containing normal images, scanned
  PDFs, multilingual text, low-quality scans, rotations, tables, empty pages,
  and adversarial large inputs.
- Measure extraction coverage, confidence distribution, latency, memory, disk,
  and retrieval usefulness.
- Require independent security and quality review before enabling OCR in an
  unattended crawl.

### Extended media after OCR

Audio/video transcription, general office-document extraction, and image-only
diagram interpretation remain separate later capabilities. They must not be
implicitly enabled by the OCR milestone.

## 9. Recommended sequence

```text
1. Complete the resumable full-corpus text harness.
2. Prove page-level resume with fault injection.
3. Run and accept Root 1 as an approximately 5,000-page text corpus.
4. Export and validate the Root 1 indexing packet.
5. Run and accept the HQ root with independent durable state and evidence.
6. Add live incremental collection and delta publication for both scopes.
7. Automate scheduling, retention, quarantine, and observability.
8. Parallelize offline CPU work.
9. Consider bounded HTTP concurrency only after measurement and approval.
10. Implement and accept the OCR track.
11. Consider audio/video and extended-media processing separately.
```

## 10. Completion language

Use precise status descriptions:

- **Controlled full-text crawl ready**: Gate A is complete.
- **Automatic recurring Confluence crawl ready**: Gates A and B are complete.
- **Two-root rollout accepted**: Root 1 and the HQ root have each passed their
  own controlled acceptance using independent durable state.
- **Scale optimized**: the relevant Gate C work has passed independent review
  and scale acceptance.
- **OCR/media complete**: only after separate OCR and binary-media contracts,
  implementation, and real acceptance; this is not implied by text-crawl
  completion.
