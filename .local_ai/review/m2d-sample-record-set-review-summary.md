# M2D Coherent Contract Sample Set Review Summary

## Patch Type

Full/squashed patch for M2D coherent Foundation contract sample set.

Apply after the accepted M2C4 state and M2C5 gate decision.

## Files Changed In Code Patch

- `tests/fixtures/__init__.py`
  - Makes the test fixture package importable.
- `tests/fixtures/foundation/__init__.py`
  - Makes Foundation fixtures importable.
- `tests/fixtures/foundation/record_factories.py`
  - Adds deterministic sample record factories that call the existing CanonicalDocument, Chunk, Relation, and ACL builders.
- `tests/fixtures/foundation/sample_record_set.py`
  - Adds a small reusable in-memory sample record set.
- `tests/foundation/contracts/test_sample_record_set.py`
  - Adds schema-validation and cross-record invariant tests.

## Workspace-Only Files Not Included In Code Patch

- `.local_ai/IMPLEMENTATION_STATE.md`
- `.local_ai/ROADMAP.md`
- `.local_ai/review/m2d-sample-record-set-review-summary.md`
- `.local_ai/review/m2d-sample-record-set.patch`

## Sample Graph

- One `CanonicalDocument`:
  - `document_id = confluence:page:123`
  - `acl_id = acl:confluence:page:123`
  - `relation_ids = [<sample relation id>]`
- One `ChunkRecord`:
  - references `document_id = confluence:page:123`
  - carries `relation_ids = [<sample relation id>]`
  - carries `acl_tags = ["space:SVMC"]`
- One `RelationRecord`:
  - `source_id = confluence:page:123`
  - `target_id = jira:issue:SPEN-1234`
  - `relation_type = mentions_jira_key`
- One `ACLRecord`:
  - references `document_id = confluence:page:123`
  - carries `acl_tags = ["space:SVMC"]`

## Invariants Tested

- All records pass `FoundationSchemaValidator`.
- Every chunk references an existing document.
- Every ACL record references an existing document.
- Every chunk `relation_id` references an existing relation.
- Chunk ACL tags are compatible with the sample ACL record.
- Record IDs are unique within each record type.
- The sample record set is deterministic.
- Mutable list values are not shared between independently built sample sets.
- Equal chunk/ACL tag values do not share the same list object inside a sample set.
- Record factories delegate to the existing Foundation record builders instead of
  hand-writing record shapes.

## Intentionally Not Implemented

- No JSONL writer.
- No manifest generation.
- No snapshot directory layout.
- No `LATEST.txt`.
- No filesystem export.
- No connector.
- No real normalization or chunking.
- No MediaAsset, SyncState, Tombstone, or Symbol fixtures.
- No embedding, indexing, retrieval, chat, Qdrant, or Gauss behavior.

## Test Command And Result

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/contracts tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
222 passed in 2.25s
```

## Patch Validation

```text
git apply --reverse --check .local_ai/review/m2d-sample-record-set.patch
passed
```
