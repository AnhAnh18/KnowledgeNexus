# Foundation-to-Indexing I0 Draft (Superseded)

Status: **superseded**

This draft, committed as `9351d60`, is superseded by
`docs/learning/IDX-I0_COMPATIBILITY_REPORT.md`.

Corrections made in the replacement report:

1. Snapshot membership is reconciled with D12's eleven-file delivery: the
   current ten-file producer set plus the required `digest-set` member.
2. Destination and event-triggered imports no longer require `LATEST.txt`;
   `use_latest` is limited to local Foundation/fixture inspection.
3. `sync_state.jsonl` is recorded as one of the eight required JSONL writer
   streams, not an optional diagnostic.
4. D9, D12, D13, and B1 are included as explicit decisions/stages and blockers.

The replacement also preserves and re-verifies the draft's valid findings about
Foundation string IDs versus UUID-oriented Qdrant IDs, missing Qdrant
ACL/provenance payload fields, direct live-store writes by `ChunkStorageService`,
and incomplete SQLite entity/activation coverage.
