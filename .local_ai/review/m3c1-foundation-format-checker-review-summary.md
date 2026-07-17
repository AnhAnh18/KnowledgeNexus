# M3C.1 Foundation Format Checker Review Summary

## Patch Type

Full/squashed patch for M3C.1, updated after review findings. Apply after the approved M3C ManifestRecordBuilder patch.

## Root Cause

`FoundationSchemaValidator` passed a `jsonschema.FormatChecker`, but the repository did not declare RFC 3339 format support as a runtime dependency. Without `rfc3339-validator`, the local `jsonschema` install treated `format: "date-time"` as effectively unenforced.

The first M3C.1 patch added a custom fallback parser. Review rejected that because the task required the standard `jsonschema.FormatChecker` path rather than a custom date-time parser.

## Explicit Dependency

Selected dependency:

- `rfc3339-validator`

Dependency file added:

- `requirements.txt`

No lock file was present in the repository, so no lock file was updated.

## Code/Test Files Included In Patch

- `requirements.txt`
- `src/knowledgenexus/shared/contracts/foundation/schema_validator.py`
- `tests/shared/contracts/foundation/test_schema_validator.py`

## Implementation Approach

- Kept one shared Foundation `_FORMAT_CHECKER = FormatChecker()`.
- Passed `_FORMAT_CHECKER` into both `Draft202012Validator` construction paths.
- Removed the custom date-time checker registration.
- Removed the custom RFC 3339 fallback parser and all helper functions.
- Kept validation errors flowing through the existing `FoundationValidationError` API.

## Supported Behavior

- `validate_record()` rejects invalid schema-facing `format: date-time` strings.
- `validate_jsonl_file()` rejects invalid date-time strings through the same `validate_record()` path.
- Valid RFC 3339 date-times with `Z`, lowercase `t`/`z`, timezone offsets, and fractional seconds pass.
- Invalid offset minutes such as `+00:60` and `+05:99` fail.
- Non-format schema validation such as required fields, patterns, and additional-property rejection remains unchanged.

## Tests Added

- Valid Manifest `generated_at`: `2026-07-13T09:30:15Z`.
- Valid Manifest `generated_at`: `2026-07-13T09:30:15+05:30`.
- Valid lowercase Manifest `generated_at`: `2026-07-13t09:30:15z`.
- Valid fractional Manifest `generated_at`: `2026-07-13T09:30:15.123456Z`.
- Invalid Manifest `generated_at`: `not-a-date`.
- Invalid Manifest `generated_at`: `2026-07-13`.
- Invalid Manifest `generated_at`: `2026-13-40T25:61:61Z`.
- Invalid Manifest `generated_at`: `2026-07-13T09:30:15+00:60`.
- Invalid Manifest `generated_at`: `2026-07-13T09:30:15+05:99`.
- Invalid Manifest JSONL record rejected with line number and `generated_at` path.
- Invalid RelationRecord `created_at` rejected to prove the fix is shared and not Manifest-specific.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r requirements.txt
Successfully installed rfc3339-validator-0.1.4 six-1.17.0

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared/contracts/foundation tests/foundation/domain/records -q
186 passed in 2.80s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared tests/foundation/domain/records -q
186 passed in 2.11s

git apply --reverse --check .local_ai/review/m3c1-foundation-format-checker.patch
passed
```

## Intentionally Not Changed

- No record builder changes.
- No schema or contract file changes.
- No exporter, snapshot writer, dataset version, or manifest builder changes.
- No datetime object support or timestamp normalization.
- No custom date-time regex, parser, or `datetime.fromisoformat()` fallback.
- No M3D implementation.

## Gate Result

- M3C complete: yes.
- M3C.1 complete: yes.
- M3D entry condition satisfied: yes.
