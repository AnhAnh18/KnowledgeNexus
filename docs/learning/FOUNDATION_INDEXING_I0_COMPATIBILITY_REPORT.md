# Foundation -> Indexing I0 Compatibility Report

Status: **frozen for I1 planning (read-only review)**  
Reviewed: 2026-08-13  
Indexing head reviewed: `203b599fc7d7c8a79e09f298386b8366908f67c3` (`feature/anh.dd1_W4-B`, `[W4-A] foundation: define evidence-bound delta inventory classification (#115)`)

## Review scope and blocker

The requested source documents were not present in either workspace checkout:

- `docs/learning/FOUNDATION_INDEXING_SNAPSHOT_HANDOFF_PLAN.md`
- `docs/learning/FOUNDATION_INDEXING_I0_GAP_REPORT.md`

Therefore their historical findings could not be re-verified verbatim. This report freezes the independently observable compatibility state from the current Indexing head and the normative contract at `contracts/foundation/Task2_Task3_Integration_Contract.md`. It does not modify Foundation code, read raw/state/evidence, or run a live crawl.

## Reusable seams

- `indexing.application.use_cases.chunk_storage_service.ChunkStorageService`: existing document/chunk persistence orchestration; suitable only behind an I2 staging adapter, not as the activation boundary.
- `DocumentRepositoryPort`, `ChunkRepositoryPort`, SQLite repositories/mappers, and ingest-job persistence: reusable storage primitives after dataset/version fields and atomic-import semantics are added.
- `EmbedderPort` and `infrastructure.embedding.bge_m3_embedder.BgeM3Embedder`: reusable for verbatim `ChunkRecord.text` embedding (1024 dimensions).
- `infrastructure.vector_store.qdrant_store.QdrantVectorStore`: reusable Qdrant connection/collection plumbing after deterministic point IDs, required filter/provenance payload, staging collection, and activation support are added.
- `contracts/foundation` shared contract loader/schema validator: preferred validation seam; Indexing must not import Foundation Python modules.

## Findings still valid / mandatory gaps before I1

1. No strict immutable snapshot resolver exists. I1 must support explicit version and `LATEST.txt`, constrain paths to `data/exports/<dataset>/<version>`, reject traversal/symlink escapes, and open the resolved 10-file set read-only.
2. No complete snapshot importer, dataset staging, verification, or activation exists. `ChunkStorageService` writes directly to live stores and cannot be used as I2's commit boundary.
3. Foundation identifiers are strings (for example `chunk:confluence:...`), while current Indexing document/chunk assumptions and Qdrant `_to_point_id` are UUID-oriented. I1/I2 must preserve the original string key and map Qdrant IDs deterministically with one pinned UUIDv5 namespace.
4. Foundation and Indexing schemas do not align field-for-field: document content/metadata, chunk `text`/heading path/hash/token fields, lowercase source axes, ACL/relation/media/symbol records, and tombstones require explicit transforms and validation.
5. Current Qdrant payload is too slim for the handoff contract: it lacks ACL/filter fields and dataset provenance/version isolation. A full snapshot must support stale sweep and config-hash invalidation.
6. SQLite schema/ports lack relation, ACL, symbol exact-lookup, media, tombstone handling, dataset-version tracking, and an atomic two-store activation barrier.
7. `SnapshotReady`, outbox, and poller automation are absent and remain post-I3 work (I4); they must consume only verified/activated versions.

## I1 entry criteria and acceptance

I1 may begin only after this compatibility report is acknowledged and the missing source-doc paths are resolved or explicitly superseded. The resolver must:

- resolve explicit version or `LATEST.txt` with exact equality to `manifest.dataset_version` and folder name;
- require `manifest.json` plus the eight required JSONL files (and tolerate optional diagnostic `sync_state.jsonl` without importing it);
- validate manifest and every JSONL record before any side effect, including unknown schema major, malformed JSON, missing fields, forbidden extras, wrong runtime types, and impossible counts;
- remain read-only, avoid Foundation module imports, and reject path traversal, symlink escape, duplicate record IDs, and checksum/count mismatches;
- return a typed snapshot descriptor that cannot represent contradictory version/path/file/count state.

## Deployment seam

The Foundation export root may be a shared mount hosted by the Indexing machine. That transport choice does not change the contract: Foundation publishes immutable version directories and `LATEST.txt`; Indexing reads only the configured published export root and never `/store/chunks`, raw, work, or streaming crawler state. `AKP_*` is legacy contract terminology, not a required directory name or runtime configuration namespace.
