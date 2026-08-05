# M10-C Independent Review

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

Verdict: NEEDS_FIX

## Findings

- P1 - Unsafe profile values are emitted into `quality_report.md`. `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_completer.py:52` accepts any non-whitespace string as `_SAFE_IDENTIFIER`, and `:72`/the renderer emit profile fields verbatim. A fresh adversarial run accepted `active_profile=r'C:\\secrets\\embedding.yaml'` and wrote `- Active profile: `C:\\secrets\\embedding.yaml``; it also accepted `https://evil.example/secret`. This violates the approved M10-C report sanitization contract (safe identifiers only; no paths, URLs, secrets, or uncontrolled strings).

- P1 - Generic mode does not reject a wrong `staging_path` runtime type before field access/side effects. `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_completer.py:163-165` calls `.exists()` directly. A fresh run passed a wrong path-like object whose `exists()` created a marker file; completion then raised sanitized `M10QualityCompletionError`, but the marker proved the untrusted object was invoked. AGENTS.md requires wrong runtime types to fail closed before field access or side effects.

- P2 - Blank JSONL lines are silently ignored by `_read_strict_jsonl_records` at `src/knowledgenexus/foundation/infrastructure/exporters/full_snapshot_staging_completer.py:350-352`. Inserting an interior blank line into `documents.jsonl` still produced a report (`accepted_blank True`) instead of rejecting malformed JSONL. This is inconsistent with the strict JSONL boundary and the shared validator's documented malformed-line behavior.

## Commands and Results

- `python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer_m10.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py --basetemp=.codex-workflow/20260805-m10/review-m10c-focused-independent` -> `42 passed, 1 skipped`.
- `python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer.py tests/foundation/infrastructure/exporters/test_full_snapshot_staging_writer.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py tests/foundation/infrastructure/exporters/test_one_page_full_snapshot_exporter.py --basetemp=.codex-workflow/20260805-m10/review-m10c-m6g-independent` -> `118 passed, 8 skipped`.
- `python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/review-m10c-arch-independent` -> `88 passed`.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` -> passed (line-ending warning only).
- Adversarial inline probes: unsafe path/URL profiles accepted and rendered; wrong path-like `exists()` side effect executed; interior blank JSONL accepted.
