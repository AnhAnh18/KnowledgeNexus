# M2C4 ACLRecordBuilder Review Summary

## Patch Type

Incremental patch for M2C4 ACLRecordBuilder.

Apply after `.local_ai/review/m2c3-relation-record-builder.patch`.

Review-fix-only patch for already-applied M2C4 work:

- `.local_ai/review/m2c4-acl-record-builder-review-fix.patch`
- Apply after `.local_ai/review/m2c4-acl-record-builder.patch`.
- Contains only the partial optional field population test.

## Files Changed In Code Patch

- `src/knowledgenexus/foundation/domain/records/acl_record_builder.py`
  - Adds `ACLRecordBuilder`, a pure helper that returns plain schema-shaped `ACLRecord` dictionaries.
- `src/knowledgenexus/foundation/domain/records/__init__.py`
  - Exports `ACLRecordBuilder` from the records package.
- `tests/foundation/domain/records/test_acl_record_builder.py`
  - Adds focused builder tests and schema-validation coverage.

## Workspace-Only Files Not Included In Code Patch

- `.local_ai/IMPLEMENTATION_STATE.md`
- `.local_ai/review/m2c4-acl-record-builder-review-summary.md`
- `.local_ai/review/m2c4-acl-record-builder.patch`

## Actual Schema Required Fields

- `schema_version`
- `acl_id`
- `document_id`
- `source_system`
- `is_restricted`
- `acl_tags`
- `acl_extraction_status`
- `extracted_at`

## Actual Schema Optional Fields

- `crawler_identity`
- `restriction_inherited`
- `restriction_source_page_ids`
- `allowed_users`
- `allowed_groups`
- `acl_confidence`

The optional fields are not nullable in the schema, so the builder omits them when the caller passes `None`.

## Behavior Implemented

- Builds a plain `dict[str, object]` for `ACLRecord`.
- Uses shared `common_constants.SCHEMA_VERSION`.
- Requires caller-supplied `acl_id`.
- Preserves caller-provided `acl_tags` exactly while copying the list.
- Includes optional fields only when they are not `None`.
- Preserves explicitly supplied empty optional lists.
- Supports partial optional field population: provided optional fields are preserved while `None` optional fields are omitted.
- Copies retained list inputs.
- Adds no unknown top-level fields.

## Lightweight Validation Implemented

- Required strings reject non-string values with `TypeError`.
- Required strings reject empty strings with `ValueError`.
- `is_restricted` accepts only actual `bool` values.
- `restriction_inherited` accepts only actual `bool` values when present.
- `acl_tags` must be a non-empty list.
- Optional list fields must be lists when present.
- Optional string fields must be strings when present.

## Intentionally Not Implemented

- No ACL extraction from Confluence.
- No Confluence restriction API calls.
- No ancestor restriction traversal.
- No deny-safe principal intersection.
- No group membership expansion.
- No user identity resolution.
- No ACL tag derivation from users or groups.
- No default-deny materialization when `acl_tags` is empty.
- No enum, regex, timestamp, ACL-tag grammar, or cross-field schema validation inside the builder.
- No exporter, importer, database, Qdrant, indexing, retrieval, chat, or Gauss behavior.

## Schema Findings

`contracts/foundation/schemas/acl_record.schema.json` matched the task analysis:

- Required and optional fields matched.
- `additionalProperties` is `false`.
- `acl_id` uses the shared `aclId` pattern.
- `document_id` uses the shared opaque ID definition.
- `source_system` allows `confluence` and `git`.
- `acl_tags` has `minItems: 1` and uses the shared ACL-tag grammar.
- `acl_extraction_status` allows `ok`, `partial`, and `unavailable`.
- `acl_confidence` allows `exact` and `approximate`.
- `extracted_at` uses the shared date-time timestamp definition.

No schema differences were discovered.

## Test Command And Result

```text
python -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
failed before pytest because `python` is not available in this shell PATH

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
212 passed in 6.96s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
212 passed in 5.94s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/records tests/foundation/domain/rules tests/shared -q
213 passed in 3.37s
```

## Patch Validation

```text
git apply --reverse --check .local_ai/review/m2c4-acl-record-builder.patch
passed

git apply --reverse --check .local_ai/review/m2c4-acl-record-builder-review-fix.patch
passed
```

## Caller Ownership

- `acl_id` remains caller-owned.
- `ACLRecordBuilder` does not call `AclIdGenerator`.
- `acl_tags` remain caller-owned final ACL representation.
- The builder preserves tags rather than deriving them from `allowed_users` or `allowed_groups`.
