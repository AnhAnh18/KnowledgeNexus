# M9-D2 Independent Review 2

Review target: current M9-D2 tree after `.codex-workflow/20260805-m9d2/08-fix-implementation.md`, against the reviewed fix plan, M8-E/M9-D1 contracts, and `AGENTS.md`. Source and test files were not modified.

## Findings

- **P2 - The required adversarial regression matrix is not committed to the focused suite.** The reviewed fix plan requires tests for every outer summary field missing, nested extra/missing fields, forged nested IDs/hashes/part metadata/wrong types, both `previous_summaries` and `current_summaries`, and zero schema-validator/projector calls for every malformed-summary case. The current focused tests cover only one outer extra-field case (`tests/foundation/domain/models/test_delta_propagation.py:113`), one constructor-time nested hash case (`tests/foundation/domain/models/test_delta_propagation.py:128`), and one previous-summary forged hash execution case (`tests/foundation/application/use_cases/test_propagate_delta.py:184`). The implementation passed an independent probe for the missing cases, but without committed regression tests these boundary guarantees can regress unnoticed. Add parametrized focused tests for the full matrix and assert atomic `summary_invalid` results and zero dependency/projector calls.

## Validation

- Focused M9-D2: `python -m pytest -q tests/foundation/domain/models/test_delta_propagation.py tests/foundation/application/use_cases/test_propagate_delta.py --basetemp=.codex-workflow/20260805-m9d2/pytest-review-2-focused` -> **23 passed**.
- M9-D1/M8-E: `python -m pytest -q tests/foundation/domain/models/test_tombstone_propagation.py tests/foundation/domain/rules/test_tombstone_record_builder.py tests/foundation/application/use_cases/test_project_tombstones.py tests/foundation/domain/models/test_chunk_stability.py --basetemp=.codex-workflow/20260805-m9d2/pytest-review-2-m9d1-m8e` -> **54 passed**.
- M9-A/B/C full bounded slice (media, attachment, Git, symbols, Jira relations) -> **194 passed, 2 skipped**.
- M8-D bounded unit/contract slice (chunking/build/CLI/config/records) -> **121 passed, 1 deselected**; the one deselected test requires an external `--tokenizer-assets-dir` fixture.
- Architecture suite: `python -m pytest -q tests/architecture --basetemp=.codex-workflow/20260805-m9d2/pytest-review-2-arch` -> **87 passed**.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` -> passed (existing LF/CRLF normalization warnings only).
- Independent adversarial probes covered all eight outer missing fields, outer extras, nested extras/missing fields, bad chunk IDs/hashes/part metadata/types in both summary tuples, wrong request runtime types, atomic zero records/count/metrics, and zero validator calls; all failed closed as required.

VERDICT: CHANGES_REQUIRED
