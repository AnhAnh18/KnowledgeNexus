# M9-C Independent Review

VERDICT: FAIL

## Findings

### P1 - Parser spans are not validated against the authority source

`ParsedSymbol.__post_init__` only checks that line/byte values are non-negative
and ordered; it has no source line/byte bounds. `BuildGitSymbols.execute`
revalidates the parser result but never compares `line_start`/`line_end`,
`start_byte`, or `end_byte` to `observation.normalized_text`. As a result, a
malicious or malformed parser result with `line_start=line_end=999` for a
one-line file is accepted and returned as `success`, with both SymbolRecord and
ChunkRecord claiming line 999. This violates the required malformed-span,
commit-bound provenance, and fail-closed boundary behavior.

Reproduction (custom parser returning a `ParsedSymbol` with line/byte values
outside the source) produced `GitSymbolIndexStatus.SUCCESS`, a symbol record
with `line_start: 999`, and a chunk with `line_start: 999`.

Affected code: `src/knowledgenexus/foundation/domain/models/symbol_index.py:106-134`
and `src/knowledgenexus/foundation/application/use_cases/build_git_symbols.py:80-84`.

### P1 - C++ extraction misses declaration-only symbols and out-of-class methods

The adapter maps only C++ `function_definition` nodes (plus aggregate nodes).
It does not implement the plan's required "declaration nodes with a
declarator" mapping, so declaration-only methods, constructors, and free
function declarations disappear. For `class A { A(); void f(int); };` the
adapter returns only the class. It also treats an out-of-class definition such
as `void A::f() {}` as a top-level `function` named `f` with qualified name
`f`, rather than a `method` under `A` (and similarly loses namespace/class
qualification for `void n::A::f()`). This makes symbol records/chunks incomplete
and gives incorrect parent/type/identity data for common C++ code.

Affected code: `src/knowledgenexus/foundation/infrastructure/parsers/tree_sitter_symbol_parser.py:143-152`.

## Verification

- `python -m pytest -q --basetemp .tmp-pytest tests/foundation/application/use_cases/test_build_git_symbols.py tests/foundation/infrastructure/parsers/test_tree_sitter_symbol_parser.py tests/foundation/domain/models/test_symbol_index.py tests/foundation/domain/records/test_chunk_record_builder.py` -> **41 passed**.
- `python -m pytest -q --basetemp .tmp-pytest tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py tests/architecture/test_m9a3_media_processing_boundary.py tests/architecture/test_m9a2_attachment_body_boundary.py tests/architecture/test_m8ac_acceptance_boundary.py` -> **26 passed**.
- `python -m compileall -q src tests` -> passed.
- `git diff --check -- src tests requirements.txt` -> passed (only CRLF normalization warnings).
- Direct tree-sitter probes confirmed missing C++ declaration symbols and
  incorrect out-of-class method classification; forged-span probe confirmed a
  successful result with impossible line metadata.

No implementation files were changed by this review.
