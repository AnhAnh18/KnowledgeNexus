# Foundation → Indexing Snapshot Handoff Plan

Status: planning only. This document does not authorize implementation.

Recommended implementation profile: `complex`.

## 1. Purpose

Close the automated handoff between the Foundation and Indexing bounded
contexts without making Foundation depend on the availability of an embedding
runtime, hydrate database, or Qdrant.

Target flow:

```text
Foundation
→ build immutable versioned snapshot
→ validate and publish atomically
→ update LATEST.txt
→ durably announce SnapshotReady for the exact published version

Indexing
→ consume the exact announced version
→ validate manifest and every record
→ apply tombstones when the snapshot is a delta
→ embed ChunkRecord.text verbatim
→ stage hydrate DB rows and Qdrant points
→ verify counts, identity, provenance and ACL payload
→ atomically activate the ingested dataset version
```

The snapshot remains the durable source of truth and replay boundary.
`SnapshotReady` is a delivery trigger, not a replacement for the snapshot.

## 2. Current verified state

Foundation already has the approved primitives for:

- versioned snapshot directories;
- deterministic JSONL streams and manifest;
- schema validation before publication;
- atomic staging-to-final publication;
- `LATEST.txt` updated after final publication;
- full snapshots and an active W4 sparse-delta implementation path.

The current checkout does not yet prove a complete Indexing importer:

- `indexing/application/use_cases/import_akp_snapshot.py` is empty;
- a BGE-M3 document embedder and Indexing ports exist;
- the concrete hydrate repositories, Qdrant writer, import job state machine,
  snapshot resolver and activation coordinator must be inspected from the
  latest Indexing branch before implementation planning is frozen;
- no production `SnapshotReady` event/outbox/consumer is currently verified.

Do not infer that absent code is unimplemented until the latest Indexing branch,
commit range or transfer patch has been inspected.

## 3. Authoritative contracts

Implementation must follow, in precedence order:

```text
contracts/foundation/schemas/
contracts/foundation/CHUNKING_SPEC.md
contracts/foundation/Task2_Task3_Integration_Contract.md
contracts/foundation/decision_logs/AI_Knowledge_Platform_v7_5_Update.md
contracts/foundation/START_HERE.md
```

Locked boundaries:

- Foundation does not import Indexing and never embeds or writes Qdrant.
- Indexing does not import Foundation Python modules.
- Both use the shared Foundation schemas and validator.
- Indexing consumes only published export snapshots, never Foundation raw/work
  directories.
- `ChunkRecord.text` is embedded verbatim; Indexing does not re-chunk it.
- Hydrate storage is the full-text source of truth. Qdrant stores vectors and a
  slim filter/provenance payload.
- ACL remains deny-safe and is carried into the Qdrant payload.
- Delta tombstones are applied before or atomically with upserts.

## 4. Non-goals

This plan does not add:

- Foundation-to-Qdrant writes;
- direct per-chunk best-effort streaming as the only handoff;
- a second copy of Foundation contracts;
- implicit Hugging Face cache access;
- Indexing re-normalization or re-chunking of Foundation records;
- retrieval, reranking, chat, OCR or media extraction;
- live Confluence work;
- scheduler policy for Foundation crawling.

## 5. Required owner decisions

These decisions must be recorded before the corresponding stage begins.

### D1 — Current Indexing source head

Resolved for I0 inspection:

```text
repository: C:\Users\SPen\Downloads\Quick Share\KnowledgeNexus\KnowledgeNexus
branch: feature/anh.dd1_W4-B
source head: 203b599fc7d7c8a79e09f298386b8366908f67c3
origin/main at inspection: 203b599fc7d7c8a79e09f298386b8366908f67c3
```

The scoped Indexing/shared/presentation/config/test tree is content-equivalent
to the previously supplied unpacked bundle after LF/CRLF normalization. Future
implementation must still start from a newly frozen head after W4 transfer and
must not assume this planning head remains current.

### D2 — Snapshot transport/location

Choose one versioned immutable location form:

1. local/shared filesystem root for the first single-host POC;
2. HTTPS artifact endpoint;
3. object-store URI.

Recommended initial choice: shared filesystem only when Foundation and Indexing
run on the same trusted host. Do not put a machine-local Windows path in an
event consumed on another host.

### D3 — Notification transport

Recommended progression:

```text
Phase 1: explicit importer CLI/API using LATEST.txt or an exact version
Phase 2: durable local outbox + Indexing poller/dispatcher
Phase 3: message broker only if operational scale requires it
```

Do not introduce Kafka/RabbitMQ solely to close the initial POC.

### D4 — Hydrate database and transaction strategy

Record the actual backend and how a staged dataset version is committed or
rolled back. SQLite and PostgreSQL require different concurrency/activation
mechanisms.

### D5 — Qdrant activation strategy

Choose and test one:

- versioned collection plus atomic alias switch; or
- one collection with a staged dataset-version filter and atomic application
  activation pointer.

Recommended: versioned collection plus alias switch for the first full-snapshot
implementation. Delta support may later use an active collection with a strict
ingest transaction/recovery ledger.

### D6 — Deterministic point namespace

Pin one permanent UUID namespace:

```text
point_id = uuidv5(POINT_ID_NAMESPACE, chunk_id)
```

Changing the namespace after production ingestion is forbidden.

### D7 — Embedding runtime

Choose local BGE-M3 or an approved document-embedding service. A query-only
`embed_query` API is not a valid document importer because it may add a query
instruction. The importer needs batch document embedding equivalent to:

```text
embed(list[ChunkRecord.text])
model = BAAI/bge-m3
dimension = 1024
normalized as required by the active profile
```

### D8 — Activation and failure semantics

Decide the availability behavior while a new version is staged. The locked
default is that readers continue using the prior active version until both
hydrate storage and Qdrant verification pass.

## 6. Stage I0 — Indexing discovery and compatibility report

No production implementation in I0.

Inspect the latest Indexing tree completely, including:

```text
src/knowledgenexus/indexing/domain/
src/knowledgenexus/indexing/application/
src/knowledgenexus/indexing/infrastructure/
src/knowledgenexus/presentation/
src/knowledgenexus/shared/contracts/
config/qdrant.collection.yaml
database migrations
Indexing, storage, embedding and retrieval tests
```

Produce a compatibility matrix covering:

- snapshot resolver;
- strict manifest/JSONL validation;
- full and delta import;
- ingest job/idempotency storage;
- document/chunk/relation/ACL/media/symbol repositories;
- tombstone application by entity type;
- BGE-M3 document embedding;
- deterministic Qdrant IDs;
- slim Qdrant payload and payload indexes;
- hydrate DB full text;
- staging and activation;
- retry/recovery;
- current API/CLI composition;
- existing dependency-boundary tests.

Output:

```text
[HANDOFF-I0] docs: reconcile Foundation snapshot and Indexing import seams
```

I0 must receive independent review before I1 scope is frozen.

## 7. Stage I1 — Strict immutable snapshot resolver

Implement an Indexing-owned resolver/reader without importing Foundation
Python modules.

Inputs:

```text
export_root
dataset_name
use_latest OR explicit dataset_version
contract_root
optional expected manifest digest
```

### LATEST.txt rules

The resolver must:

1. accept only an absolute configured export root;
2. require the dataset directory and pointer to be regular, non-symlink,
   non-reparse objects;
3. read a bounded `LATEST.txt` as strict UTF-8;
4. require exactly `<dataset_version>\n`, with one non-empty line;
5. reject path separators, dot components, control characters and unexpected
   whitespace;
6. resolve the version as a direct child of the configured dataset root;
7. require the immutable version directory and expected file set;
8. validate `manifest.dataset_name` and `manifest.dataset_version` against the
   configured name, pointer/explicit version and directory name;
9. when a digest is supplied by `SnapshotReady`, hash the exact manifest bytes
   and compare before parsing/import;
10. bind the opened version/digest for the entire import; never re-read
    `LATEST.txt` midway.

### Validate-before-write

Before any storage mutation:

- validate manifest schema and supported schema/profile versions;
- validate every JSONL record against the correct shared schema;
- reject duplicate IDs, blank lines, duplicate JSON keys, NaN/infinity,
  malformed UTF-8, unexpected files and count mismatches;
- verify deterministic stream identities and cross-stream closure required by
  the active snapshot mode;
- reject delta snapshots without a resolvable accepted base chain;
- verify profile/model/dimension compatibility.

The reader must be bounded by explicit byte, record and path limits and return
ownership-isolated records or a safe streaming handle bound to verified bytes.

Candidate:

```text
[HANDOFF-I1] indexing: resolve and validate immutable Foundation snapshots
```

## 8. Stage I2 — Idempotent Indexing import core

Implement `ImportAkpSnapshot` as an Indexing application use case over injected
ports.

### Import job identity

Use a durable identity at least equivalent to:

```text
dataset_name + dataset_version + manifest_digest + importer_profile_version
```

The same successful job is idempotent. A conflicting digest for the same
dataset version fails closed.

### Full snapshot behavior

1. create a staged ingest job;
2. map and stage all supported Foundation records;
3. batch `ChunkRecord.text` exactly as delivered;
4. call document embedding, never `embed_query`;
5. verify vector count, dimension, finiteness and model identity;
6. store full chunk text and metadata in hydrate storage;
7. store vector plus slim payload in Qdrant;
8. verify record/vector counts and deterministic point IDs;
9. mark the staged version ready for activation.

### Delta behavior

1. require the accepted base dataset/version currently active;
2. validate the complete delta/base chain;
3. apply tombstones by `entity_type` before corresponding upserts;
4. embed only new or index-invalidated chunk text;
5. update ACL/filter payload even when chunk text is unchanged;
6. ensure removed Qdrant points and hydrate rows cannot remain visible;
7. fail closed if a delta targets a different active base.

### Required payload provenance

Each Qdrant point must include the approved slim fields, including:

```text
chunk_id
document_id
dataset_name
dataset_version
source_system
source_type
content_kind
language
acl_tags
source-specific filter fields
source_version/updated_at
chunker_version
embedding_model
config_hash
```

Full text remains in hydrate storage, not Qdrant.

Candidate:

```text
[HANDOFF-I2] indexing: stage idempotent Foundation snapshot imports
```

## 9. Stage I3 — Verified two-store activation

An import is not active merely because all writes returned success.

Before activation verify:

- expected manifest counts against staged hydrate rows;
- expected chunk count against staged Qdrant points;
- deterministic point-ID round trips;
- vector dimension/model identity;
- required payload and ACL indexes;
- no unresolved write failures;
- delta tombstones and replacement counts;
- sampled hydrate/Qdrant provenance agreement;
- staged version identity equals the bound import job.

Activation must switch the application-visible version only after both stores
pass. A failure leaves the previous version active and records a resumable or
terminal sanitized job state. Never expose a partially staged version to
retrieval.

Candidate:

```text
[HANDOFF-I3] indexing: verify and activate staged snapshot versions
```

## 10. Stage I4 — Durable SnapshotReady automation

Add automation only after the explicit importer and activation path are
approved.

### Event contract

Create a small versioned shared contract. Minimum envelope:

```json
{
  "format_version": "1.0",
  "event_id": "<deterministic or durable unique identity>",
  "event_type": "SnapshotReady",
  "dataset_name": "spen_knowledge_poc",
  "dataset_version": "<immutable version>",
  "manifest_sha256": "<lowercase sha256>",
  "snapshot_location": "<approved URI or location reference>"
}
```

Do not include credentials, raw paths inappropriate for the consumer host,
source IDs, titles, content or ACL principals.

### Foundation producer

- emit only after final snapshot publication and successful `LATEST.txt`
  update;
- derive the event from the exact published manifest bytes;
- persist the event in a durable no-clobber outbox before delivery;
- use at-least-once delivery with bounded retry;
- never roll back a valid snapshot because Indexing is unavailable;
- retain pending events across process restart;
- include a reconciliation command that derives missing events from immutable
  published versions and the delivery ledger.

Because filesystem publication and event transport are not one transaction,
the reconciliation path is mandatory. A successful snapshot must not become
permanently invisible merely because notification failed.

### Indexing consumer

- validate the event before resolving the snapshot;
- use the exact `dataset_version` and digest from the event, not the current
  value of `LATEST.txt`;
- deduplicate by event/import-job identity;
- acknowledge only after the import has reached an approved terminal state;
- tolerate duplicate and out-of-order delivery;
- reject a conflicting digest/version binding;
- expose aggregate sanitized status only.

Candidate commits:

```text
[HANDOFF-I4-A] foundation: publish durable snapshot-ready notifications
[HANDOFF-I4-B] indexing: consume snapshot-ready import requests
```

These two commits require separate bounded-context and integration reviews.

## 11. Stage I5 — End-to-end acceptance

No live Confluence call is required. Use already published, sanitized test
snapshots or deterministic fixtures.

Mandatory scenarios:

1. Publish a full Foundation snapshot, deliver `SnapshotReady`, import, embed,
   stage, verify and activate it.
2. Repeat the same event: zero duplicate rows/points and no re-embedding unless
   explicitly required.
3. Lose delivery after publication: reconciliation recreates/delivers the
   pending event without republishing the snapshot.
4. Deliver duplicate/out-of-order events: exact version imports remain
   deterministic and the active-version policy is preserved.
5. Corrupt pointer, event digest, manifest, JSONL record, count or schema:
   zero storage mutation.
6. Simulate hydrate success and Qdrant failure: old version remains active.
7. Simulate Qdrant success and hydrate failure: old version remains active and
   staging is recoverable/cleanable.
8. Import a delta bound to the active full snapshot; verify tombstones in both
   stores before replacement upserts.
9. ACL-only delta updates Qdrant filtering payload and hydrate metadata without
   changing embedded text unnecessarily.
10. Config/model invalidation triggers the required re-embedding.
11. Query retrieval through the active alias/version and hydrate the exact
    original chunk text.
12. Network, filesystem, symlink/reparse, path traversal, retry and resource
    exhaustion failures remain sanitized and bounded.

Acceptance evidence must contain aggregate counts and booleans only. It must
not contain chunk text, page IDs, local paths, credentials, raw payloads or full
artifact hashes.

## 12. Review and commit workflow

Do not implement the entire handoff as one PR.

Recommended stack:

```text
I0 — discovery/contract reconciliation
I1 — resolver and validate-before-write
I2 — importer and staged persistence
I3 — two-store verification/activation
I4-A — Foundation outbox producer
I4-B — Indexing consumer
I5 — end-to-end acceptance and closeout
```

After each stage:

1. run focused and affected regression suites;
2. run `compileall` and `git diff --check`;
3. stop with a clean review candidate;
4. obtain independent review in a fresh session that makes no edits;
5. fix confirmed findings in a separate fixer session;
6. obtain focused independent re-review;
7. freeze the approved head before starting the next stage.

Do not call a self-review independent. Do not merge stages merely to reduce PR
count; a final squash may be chosen by the owner only after the complete stack
has been independently reviewed and remains bisectable in its review history.

## 13. Immediate next action

While Foundation W4 is in progress, perform I0 only:

```text
obtain latest Indexing branch/patch
→ inspect actual importer/storage/Qdrant state
→ produce compatibility and gap report
→ resolve D1-D8
→ independent plan review
```

Do not start SnapshotReady production code before the snapshot importer can
successfully import and activate an explicitly selected immutable version.
