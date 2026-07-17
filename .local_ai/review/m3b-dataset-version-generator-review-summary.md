# M3B DatasetVersionGenerator Review Summary

## Patch Type

Full/squashed patch for M3B DatasetVersionGenerator.

Apply after the accepted M3A JsonlRecordWriter state.

## Files Changed In Code Patch

- `src/knowledgenexus/foundation/domain/rules/dataset_version_generator.py`
  - Adds the pure deterministic dataset_version formatter.
- `src/knowledgenexus/foundation/domain/rules/__init__.py`
  - Exports `DatasetVersionGenerator` from the public rules package.
- `tests/foundation/domain/rules/test_dataset_version_generator.py`
  - Adds focused tests for exact formatting, UTC conversion, determinism,
    invalid inputs, Windows-safe characters, and equivalent instants.

## Workspace-Only Files Not Included In Code Patch

- `.local_ai/IMPLEMENTATION_STATE.md`
- `.local_ai/ROADMAP.md`
- `.local_ai/review/m3b-dataset-version-generator-review-summary.md`
- `.local_ai/review/m3b-dataset-version-generator.patch`

## Public API

```python
DatasetVersionGenerator.generate(
    *,
    instant: datetime,
) -> str
```

## Dataset Version Convention

```text
vYYYYMMDD-HHMMSS-ffffffZ
```

Example:

```text
v20260713-093015-123456Z
```

The convention is a Foundation producer policy. `manifest.schema.json` remains
unchanged and still treats `dataset_version` as a non-empty string.

## UTC And Timezone Behavior

- `instant` must be a timezone-aware `datetime`.
- Non-UTC timezone-aware inputs are converted to UTC before formatting.
- Equivalent instants expressed with different offsets produce the same
  dataset_version.
- Naive datetimes, including `tzinfo is None` or `utcoffset() is None`, raise
  `ValueError`.
- Non-datetime inputs raise `TypeError`.

## Deterministic Clock Boundary

The generator does not acquire the current time. A later caller or use case must
obtain one instant and pass it into this pure rule.

No `ClockPort` was added because M3B only defines the deterministic formatting
rule. A later application or snapshot orchestration task can own the clock port
or current-time acquisition boundary.

## Collision And Idempotency Boundary

- Identical instants intentionally produce identical dataset versions.
- Microsecond precision reduces accidental collisions but does not guarantee
  global uniqueness.
- The generator does not inspect `data/exports`, existing folders, process IDs,
  hostnames, counters, or random values.
- Existing-folder collision handling belongs to a later snapshot writer.

## Intentionally Not Implemented

- No ManifestRecordBuilder.
- No manifest `generated_at` formatter.
- No manifest writing.
- No JSON Schema or contract changes.
- No snapshot directory creation.
- No staging directory behavior.
- No `LATEST.txt`.
- No ClockPort.
- No export orchestration.
- No connector, indexing, retrieval, chat, Qdrant, or Gauss behavior.

## Test Command And Result

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules tests/foundation/infrastructure/exporters tests/shared -q
126 passed in 2.25s
```

Focused test:

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/rules/test_dataset_version_generator.py -q
16 passed in 0.50s
```

## Patch Validation

```text
git apply --reverse --check .local_ai/review/m3b-dataset-version-generator.patch
passed
```

## Differences From Prompt

None.
