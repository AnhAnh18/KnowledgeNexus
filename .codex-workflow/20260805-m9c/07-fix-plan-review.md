RECOMMENDED_IMPLEMENTATION_PROFILE: build

# M9-C Fix Plan Review

The two bounded fixes target both confirmed P1 findings and do not require a
broader seam change. The plan is buildable, but the following details must be
made explicit so the implementation and re-review can verify the M9-C
contract rather than only exercise the happy path.

## Required span-validator detail

1. Run validation for every parser symbol immediately after validating the
   parser result type, path, language, and status, and before either symbol
   records or zero-symbol fallback chunks are built. A malformed symbol in a
   later authority file must roll back records/chunks already built for earlier
   files.
2. Define the coordinate contract in the fix: `line_start`/`line_end` are
   inclusive one-based source lines; `start_byte`/`end_byte` are exclusive
   UTF-8 byte offsets into the exact normalized authority text. Derive line
   count and byte-to-line boundaries from that text, not from parser claims or
   decoded character counts. Reject zero/negative lines, reversed ranges,
   `end_byte > len(source_text.encode("utf-8"))`, and spans whose byte-derived
   lines cannot be contained by the declared line range. A leading attached
   comment may extend `line_start` before the node byte start, but must still be
   within the source and declared range.
3. The validator must also reject symbol path/language mismatches and malformed
   runtime symbol objects as `parser_result_invalid`; it must not permit a
   parser result with no symbols to bypass validation of its own result
   invariants. The failed result must contain no records, chunks, or metrics,
   including when a tokenizer/schema call has already occurred for an earlier
   symbol.

Add focused regressions for line overflow, byte overflow, zero and reversed
   ranges, a UTF-8 multibyte offset, byte/line-range mismatch, and path or
language mismatch. Assert `parser_result_invalid`, empty output, and atomic
rollback. Retain the existing `object()`, `None`, forged-result, and wrong
status adversarial cases.

## Required C++ mapping detail

1. Specify that the adapter recognizes only declaration nodes with a direct
   function declarator (plus `function_definition`), and does not emit nested
   declarator helper nodes as duplicate symbols. Name and qualifier extraction
   must walk the declarator structure, including `qualified_identifier`,
   constructor/destructor, and operator forms.
2. Qualified out-of-class symbols are top-level in the syntax tree, so the
   adapter needs a deterministic class/struct-qualified-name lookup (or an
   equivalent prior declaration pass). A namespace qualifier alone remains a
   `function`; a qualifier resolving to a class/struct is a `method`. Preserve
   the full qualifier in `qualified_name` and use the nearest class-qualified
   name as `parent_qualified_name`.
3. State the expected constructor rule explicitly: `A();` and
   `A::A()` have `name == "A"`, `symbol_type == "method"`, and the enclosing
   class qualified name as parent. Declaration-only free functions remain
   `function`. Their line/byte spans and signatures must be the declaration
   node span, not a child declarator span.

Add one fixture/assertion set covering: an in-class constructor and method
declaration, a free function declaration, `void A::f() {}`, `void n::A::f();`,
and a namespace-qualified free function such as `void n::g();`. Assert exact
symbol type, name, qualified name, parent, source order, line spans, symbol
IDs, and emitted chunk linkage; assert no duplicate symbol for each declaration.
Include a nested namespace/class case to prove that `n::A::f` keeps both
qualifiers and is not flattened to `f`.

## Acceptance

After these clarifications, the existing focused M9-C suite plus the new
regressions, M9-B/M9-A/M8-D/E regressions, architecture checks, `compileall`,
and `git diff --check` are sufficient. The required fresh independent
re-review and `VERDICT: PASS` gate remain unchanged. No M9-B behavior,
fallback policy, regex parsing, or unrelated symbol vocabulary should be
expanded by this fix.
