# M9-C Review-Fix Plan

## Confirmed findings

- P1: parser-provided byte/line spans are not checked against the authority
  observation before records/chunks are emitted.
- P1: the C++ adapter omits declaration-only function/method/constructor nodes
  and misclassifies out-of-class qualified definitions as top-level functions.

## Bounded fixes

1. Add an application-boundary span validator immediately after parser-result
   validation and before any record/fallback construction. Treat
   `line_start`/`line_end` as inclusive one-based source lines and
   `start_byte`/`end_byte` as exclusive UTF-8 offsets in the exact normalized
   observation text. Derive byte-to-line boundaries from that text; reject path
   or language mismatch, zero/reversed/out-of-range lines, byte overflow, and
   byte/line mismatch (including multibyte UTF-8). A malformed symbol in any
   later file rolls back all earlier in-memory output and returns sanitized
   `parser_result_invalid`. Add forged-span tests for every case.
2. Extend only the tree-sitter C++ mapping for direct declaration nodes whose
   declarator contains a function declarator, without emitting helper nodes.
   Walk qualified identifiers, constructors/destructors, and operators. Resolve
   out-of-class qualifier chains against the prior class/struct declarations:
   a class-qualified chain is a method with the nearest class parent; a
   namespace-only chain remains a function. `A();` and `A::A()` are methods
   named `A`; free declarations remain functions. Add fixtures for in-class
   declarations, free declarations, `void A::f() {}`, `void n::A::f();`, and
   `void n::g();`, with exact IDs/ranges/parents and no duplicates. Do not add
   regex or broaden to call graph/fields.

## Validation

- Focused M9-C tests including all existing adversarial cases and the new P1
  regressions.
- M9-B, M9-A, M8-D/E, architecture, compileall, and diff-check regressions.
- Fresh independent re-review in a new session; no ledger update or commit until
  `VERDICT: PASS`.
