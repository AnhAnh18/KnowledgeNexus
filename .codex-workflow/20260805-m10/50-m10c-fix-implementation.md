# M10-C Fix Implementation

Implemented the approved bounded remediation for all findings in the
independent review. Generic mode now uses a strict profile identifier grammar,
accepts only the concrete platform `Path` type before any path method, and
rejects blank JSONL lines. The legacy one-page/M6G branch is unchanged.

Added adversarial tests for unsafe Windows/Unix paths and URLs, wrong path
runtime values including a side-effecting path-like object, and trailing or
interior blank JSONL lines.

## Validation

```text
py -m pytest -q --basetemp=.pytest-m10c-fix-focused2 tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer_m10.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py
50 passed, 1 skipped

py -m pytest -q --basetemp=.pytest-m10c-fix-m6g tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py tests/foundation/infrastructure/exporters/test_one_page_full_snapshot_exporter.py
118 passed, 8 skipped

py -m pytest -q --basetemp=.pytest-m10c-fix-arch tests/architecture
88 passed

py -m compileall -q src tests
passed

git diff --check
passed (line-ending warning only)
```

No roadmap/state, CLI, writer, publisher, connector, network, or commit/push
changes were made.
