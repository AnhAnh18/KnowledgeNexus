RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-D/E Independent Review

Scope reviewed: `.local_ai/ROADMAP.md` M10 section, approved plan/critique artifacts `52`-`54`, implementation report `55`, current M10 source/tests, application/import wiring, CLI mapping, M3 writer/completer/publisher seams, and the M10-A/B/C/M6G/M8/M9 regression surfaces. No source, test, roadmap, or state files were edited.

## Findings

### P1 - Acceptance failure leaves the new pointer advertised

`src/knowledgenexus/foundation/application/use_cases/export_m10_snapshot.py:321-331` maps any post-publication readback failure to `acceptance` but does not restore the pre-publication `LATEST.txt` bytes or remove/quarantine the newly advertised final directory. A mutating publisher probe delegated to `FullSnapshotPublisher`, then changed `quality_report.md`; the use case raised `acceptance`, but `LATEST.txt` changed from the old pointer to `v20260805-000000-000000Z\n` and the tampered final directory remained. This violates the approved postcondition to preserve the old pointer where possible and means a failed acceptance can leave a corrupt snapshot as the advertised one.

### P1 - Readback trusts a mutable injected validator

`src/knowledgenexus/foundation/application/use_cases/export_m10_snapshot.py:232-239` validates parsed manifest/records in place and never checks that the validator left them unchanged (unlike the M10-C completer). A stateful exact-`FoundationSchemaValidator` probe tampered the published `manifest.json` on disk to `dataset_version: wrong-version`, then mutated the parsed manifest back during the fourth manifest validation call. The use case returned `published` while the final file still contained `wrong-version`. Strict post-publication acceptance must validate an isolated copy and reject validator mutation, or use a separately trusted canonical validator for readback.

### P2 - Non-integer `SystemExit` escapes the CLI sanitizer

`src/knowledgenexus/foundation/cli/export_m10_snapshot.py:97-98` does `int(exc.code or 0)` without guarding conversion. An adversarial boundary probe monkeypatched `_parse_args` to raise `SystemExit("secret")`; `cli.main([])` raised `ValueError: invalid literal for int() with base 10: 'secret'` instead of returning a sanitized exit code/JSON diagnostic. Real argparse paths currently use integer codes, but the public boundary should fail closed for every `SystemExit` payload.

### P2 - Digest errors occur outside the sanitized failure mapping

`src/knowledgenexus/foundation/application/use_cases/export_m10_snapshot.py:332` computes `_snapshot_digest(final_path)` after the acceptance `try` block. A probe replacing `_snapshot_digest` with `RuntimeError("secret path")` produced that raw exception after publication, bypassing the closed M10 failure categories. A filesystem race or read failure at this final step has the same shape; digest computation should be inside the sanitized post-publication handling.

## Verification

Focused M10-D/E and architecture:

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/cli/test_export_m10_snapshot_cli.py tests/foundation/application/use_cases/test_export_m10_snapshot.py tests/foundation/integration/test_m10_synthetic_acceptance.py tests/architecture/test_application_import_boundary.py --basetemp=.codex-workflow/20260805-m10/56-pytest-m10de-focused-final
35 passed in 0.73s
```

Regression suites:

```text
$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/domain/models/test_m10_snapshot.py tests/foundation/domain/models/test_m10_composition.py tests/foundation/application/use_cases/test_compose_m10_snapshot.py --basetemp=.codex-workflow/20260805-m10/56-pytest-m10abc
51 passed in 0.74s

$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/contracts/test_one_page_export_m6g_b_consistency.py tests/foundation/integration/test_golden_full_snapshot_export.py tests/foundation/application/use_cases/test_project_one_page_export.py --basetemp=.codex-workflow/20260805-m10/56-pytest-m6g
37 passed in 1.38s

$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/domain/models/test_chunk_stability.py tests/foundation/application/use_cases/test_process_confluence_media_attachment.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m10/56-pytest-m8m9
125 passed in 0.83s

$env:PYTHONPATH='src'; python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m10/56-pytest-architecture
89 passed in 1.37s

$env:PYTHONPATH='src'; python -m pytest -q tests/foundation/infrastructure/exporters/test_full_snapshot_staging_completer_m10.py tests/foundation/infrastructure/exporters/test_full_snapshot_publisher.py --basetemp=.codex-workflow/20260805-m10/56-pytest-m3-export
47 passed, 6 skipped in 1.30s

python -m compileall -q src tests
completed successfully

git diff --check
completed successfully (only existing LF/CRLF warnings)
```

Additional probes confirmed malformed requests fail before adapter calls, existing staging is rejected before adapter calls, application import loads no `knowledgenexus.foundation.infrastructure` modules, and the deterministic synthetic export produces the required ten files. The P1/P2 findings above prevent a clean independent `PASS` until bounded fixes and a fresh re-review.
