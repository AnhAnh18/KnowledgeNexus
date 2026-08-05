# M9-C Review-Fix Implementation

Addressed both confirmed P1 findings from `05-review-1.md`:

- Added an atomic application-boundary validator for parser UTF-8 byte spans,
  inclusive one-based line ranges, path/language provenance, and source bounds.
  Invalid later-file output cannot escape earlier in-memory work.
- Extended the tree-sitter C++ adapter for direct function declarations,
  constructors, and qualified out-of-class definitions. Class-qualified chains
  resolve to methods with full namespace/class names; namespace-only chains
  remain functions. Declaration/definition duplicates are deterministically
  coalesced by canonical signature, preferring a body-bearing definition.
- Added regressions for forged line spans and declaration/qualified-method
  extraction.

Focused fix validation:

- `python -m pytest -q tests/foundation/infrastructure/parsers/test_tree_sitter_symbol_parser.py tests/foundation/application/use_cases/test_build_git_symbols.py --basetemp=.pytest-m9c-fix` -> `7 passed`.
- Final focused M9-C set -> `10 passed`; M9-B `27 passed`; M8-D/E `40 passed`;
  M9-A `65 passed`; architecture `85 passed`; compileall and diff-check passed.
- Fresh independent re-review: `.codex-workflow/20260805-m9c/09-review-2.md`,
  `VERDICT: PASS`, no P0-P3 findings.
