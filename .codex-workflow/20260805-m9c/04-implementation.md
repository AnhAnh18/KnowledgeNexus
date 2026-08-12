# M9-C Implementation Report

## Scope

Implemented the bounded `BuildGitSymbols` authority stream over the approved
M9-B `CodeDocumentPlan` without changing M9-B fallback-plan invariants. Added a
tree-sitter C++/Java parser adapter, runtime-validated symbol/index models,
deterministic symbol IDs, schema-valid SymbolRecord and code-symbol/fallback
ChunkRecord construction, exact dependency pins, and adversarial-focused tests.

## Files

- `requirements.txt`
- `src/knowledgenexus/foundation/domain/models/symbol_index.py`
- `src/knowledgenexus/foundation/domain/rules/symbol_id_generator.py`
- `src/knowledgenexus/foundation/domain/rules/symbol_record_builder.py`
- `src/knowledgenexus/foundation/ports/symbol_parser_port.py`
- `src/knowledgenexus/foundation/infrastructure/parsers/tree_sitter_symbol_parser.py`
- `src/knowledgenexus/foundation/application/use_cases/build_git_symbols.py`
- package exports under `src/knowledgenexus/foundation/{domain,ports,application}`
- focused tests under `tests/foundation/{domain,infrastructure,application}`

Pinned parser dependencies:

- `tree-sitter==0.25.2`
- `tree-sitter-cpp==0.23.4`
- `tree-sitter-java==0.23.5`

## Validation

- `python -m pytest -q tests/foundation/infrastructure/parsers/test_tree_sitter_symbol_parser.py tests/foundation/domain/models/test_symbol_index.py tests/foundation/application/use_cases/test_build_git_symbols.py --basetemp=.pytest-m9c-focused-final` -> `10 passed` after review fixes.
- `python -m pytest -q tests/foundation/application/use_cases/test_build_git_code_documents.py tests/foundation/domain/models/test_git_code_source.py --basetemp=.pytest-m9c-m9b` -> `27 passed`.
- `python -m pytest -q tests/foundation/application/use_cases/test_process_confluence_page_set.py tests/foundation/domain/models/test_confluence_page_set.py tests/foundation/domain/models/test_chunk_stability.py --basetemp=.pytest-m9c-m8de` -> `40 passed`.
- M9-A media regression selection -> `65 passed`.
- `python -m pytest -q tests/architecture --basetemp=.pytest-m9c-arch` -> `85 passed`.
- `python -m compileall -q src tests` -> passed.
- `git diff --check` -> passed (only normal LF/CRLF warnings from Git).

Fresh independent re-review completed at `.codex-workflow/20260805-m9c/09-review-2.md`
with `VERDICT: PASS` and no P0-P3 findings.
