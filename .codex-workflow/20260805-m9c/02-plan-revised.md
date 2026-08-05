# M9-C Minimal Symbol Index - Revised Bounded Plan

## Review disposition

The independent critic classified this stage as `complex` and identified five
P1 gaps: the M9-B authority seam migration, distinct symbol/chunk IDs, parse
status/fallback policy, complete ChunkRecord semantics, and deterministic
symbol naming/rendering. This revision resolves those gaps before implementation.

## Objective and seam choice

M9-C adds a second, atomic application boundary `BuildGitSymbols` that consumes
an already validated M9-B `CodeDocumentPlan` and emits a `GitSymbolIndexResult`.
M9-B's approved plan remains unchanged: it continues to emit documents and
non-authority `code_window` chunks while retaining authority observations with
zero fallback chunks. M9-C validates that the authority observations are exact
byte/text/path/commit matches to the plan, then returns symbol records and
authority chunks for later M9-D composition. No M9-B result is mutated or
partially rewritten in this stage.

This shape keeps the M9-B gate stable while making the cross-plan identity
contract explicit. M9-D will be responsible for composing the M9-B fallback
stream and this M9-C authority stream into one code snapshot.

## Normative authority

- `contracts/foundation/decision_logs/AI_Knowledge_Platform_Master_Spec_v7_1.md` §§12.1-12.2.
- `contracts/foundation/CHUNKING_SPEC.md` §§3, 5.1-5.4, 6-7.
- `contracts/foundation/schemas/symbol_record.schema.json` and `defs.schema.json`.
- `contracts/foundation/schemas/chunk_record.schema.json`.
- Existing `GitRepositorySnapshot`, `CodeDocumentPlan`, active BGE-M3 profile,
  `ChunkRecordBuilder`, and M9-B commit/path policy.

## Public models and runtime invariants

Add immutable, exact-type validated models under the Foundation domain:

- `ParsedSymbol`: `path`, `language`, `symbol_type`, `name`,
  `qualified_name`, nullable `signature`, one-based `line_start`/`line_end`,
  nullable `parent_qualified_name`, attached leading comment text, and
  `parse_status`. Spans must be within the source line count and source order
  must be deterministic.
- `SymbolParseResult`: `status` (`ok`/`partial`), ordered symbols, parser
  diagnostics reduced to bounded category/counters, and source path/language.
- `GitSymbolIndexResult`: `status` (`success`/`failed`), ordered
  `symbol_records`, ordered `chunks`, metrics (`authority_file_count`,
  `symbol_count`, `chunk_count`, `partial_file_count`, `fallback_file_count`,
  `oversized_part_count`), and one sanitized failure category on failure.
  Success has no error and internally consistent counts; failure has no records,
  chunks, or metrics other than zeroes.
- `BuildGitSymbolsRequest`: exact `CodeDocumentPlan`, active
  `ChunkingProfile`, and explicit RFC3339 `scanned_at` supplied by the caller.
  The timestamp is normalized once and reused for every record; no wall clock
  is read by the use case.

Every public constructor/use-case validates runtime types before field access;
rejects `object()`, `None`, wrong enum values, missing/extra fields, forged
dataclass instances, impossible counters, duplicate paths/IDs, and invalid
commit/path provenance. Unexpected dependency exceptions become sanitized
failure categories and never leak partial output.

## Parser capability and exact dependency pin

Add `SymbolParserPort` under `foundation/ports`. The application imports only
this port. Add one infrastructure adapter using official tree-sitter grammars:

- `tree-sitter==0.25.2` (the grammar wheels expose the current `PyCapsule`
  language API; the older 0.22 constructor is incompatible with these official
  Windows wheels)
- `tree-sitter-cpp==0.23.4`
- `tree-sitter-java==0.23.5`

The adapter uses the 0.25 `Parser(Language(grammar.language()))` API and grammar
module language factories; it never downloads grammars or falls back to
regex/ad-hoc parsing.
An offline smoke test parses one C++ and one Java fixture with those installed
packages. Kotlin/XML and all non-authority extensions remain outside this
adapter and keep M9-B fallback-window behavior.

## Deterministic extraction contract

The adapter traverses tree-sitter nodes in `(start_byte, end_byte, node_type)`
order with a parent stack. The following mappings are the only extracted types:

| Language | Tree-sitter declarations | `symbol_type` | Qualified-name rule |
|---|---|---|---|
| C++ | `namespace_definition` | `namespace` | `A::B` by enclosing namespace stack |
| C++ | `class_specifier` | `class` | enclosing namespace/class + name |
| C++ | `struct_specifier` | `struct` | same |
| C++ | `enum_specifier` | `enum` | same |
| C++ | `function_definition`, declaration nodes with a declarator | `function` or `method` | enclosing class => method; otherwise function |
| Java | `package_declaration` | `package` | dotted package name |
| Java | `class_declaration`, `interface_declaration`, `enum_declaration` | `class`, `interface`, `enum` | enclosing package/class + name |
| Java | `method_declaration`, `constructor_declaration` | `method` | enclosing class + name |

Anonymous declarations, fields/variables, references, calls, templates as
instantiations, and unsupported node forms are not emitted. Constructors use
the class name as `name`; operators retain their canonical source spelling.
Multiline declarations use the exact normalized source signature slice with
internal whitespace collapsed only where the grammar slice contains line
breaks; no semantic reformatting is performed. Parent links use the parent's
qualified name. Leading comments are the contiguous preceding comment block,
allowing annotations/preprocessor lines only when they are part of the same
attached source span; a comment is included once in the symbol's rendered text.

Stable ordering is source order, then parent depth, then symbol type/name. For
same-file same-qualified-name overloads, `SymbolIdGenerator` emits:
`{repo}:{branch}:{file_path}:{qualified_name}` for the first/unique symbol and
`~{sha256(signature)[:8]}` for each overload. Duplicate signatures are a
deterministic duplicate error rather than silent record replacement.

## Parse-state matrix

| Parser state | Symbol records | Chunks | Application result |
|---|---|---|---|
| clean tree, symbols found | records `parse_status=ok` | one `code_symbol` per symbol (or parts) | success |
| partial tree, symbols found | extracted records `parse_status=partial` | only extracted `code_symbol` chunks; no duplicate windows | success |
| clean/partial tree, zero symbols | none | M9-C emits bounded `code_window` fallback for that authority file | success |
| parser hard failure / malformed parser result | none | none | failed `parser_failed`/`parser_result_invalid` |
| Kotlin/XML/non-authority | none from M9-C | unchanged M9-B `code_window` stream | success at M9-B; M9-C ignores |

Only the zero-symbol authority case uses §5.4 fallback windows. No fallback is
invented for a partial parse that already yielded symbols. A parser error does
not abort extraction of valid nodes, but a transport/API failure fails the
atomic M9-C result.

## Symbol records and code-symbol chunks

`SymbolRecordBuilder` returns a plain dict with exactly the schema fields,
validates it through `FoundationSchemaValidator`, and binds `repo`, `branch`,
`commit_hash`, `file_path`, language, line range, `parse_status`, and shared
`scanned_at` to the validated authority observation. `chunk_id` is non-null for
every emitted symbol and points to exactly one emitted symbol chunk.

Chunks are built through `ChunkRecordBuilder` with the complete required field
set: `acl_tags=["repo:spen-sdk"]`, empty `jira_keys`/`relation_ids` and
`heading_path`, `source_version=commit_sha`, `repo`, `branch`, `file_path`,
`symbol`, line metadata, active `chunker_version=1.2.0`, BGE-M3 token count,
and content hash of the exact normalized text. Schema validation occurs before
return. The provenance prefix is normalized and included in both token count
and hash:

`// spen-sdk · {file_path} · {qualified_name}` followed by one blank line.

Aggregate class/struct/interface/enum chunks contain the declaration and
member-signature spans only; method/function chunks contain the declaration/body
source span. Aggregate text may be non-contiguous; its `line_start`/`line_end`
are the minimum/maximum source lines covering the selected spans and are checked
against the commit-bound source. Attached comments are included once.

For an oversized function/method, split complete source lines only using the
active BGE-M3 tokenizer/profile (`code_window_target_tokens`, hard maximum,
40-line cap, 4-line overlap). Repeat the prefix/comment in every part, set
contiguous `part_index`/`part_total`, use unit keys
`qualified_name#p{n}`, and fail closed as `unsplittable_code_line` when one line
cannot fit. Aggregate symbols are bounded by the same hard maximum; an
unsplittable aggregate fails closed.

`ChunkIdGenerator` receives the stable Git document key
`git:{repo}:{file_path}`, the unit key above, and exact normalized chunk text.
Branch and commit are excluded from chunk IDs. Symbol IDs remain branch-bound.
Byte-identical duplicate chunks receive deterministic `-1`, `-2` suffixes only
when the duplicate unit is intentionally repeated; a true hash collision for
different preimages fails closed as `chunk_id_collision`.

## Atomic use-case algorithm

1. Validate request, active profile, parser/tokenizer/schema dependencies, and
   the exact M9-B plan before any parser/tokenizer call.
2. Derive authority observations from the plan and revalidate path, source bytes,
   normalized text, repo/branch/commit, and authority flag against the plan's
   canonical observations.
3. Parse each authority file using the port; validate every returned node/span,
   language, parent, status, and deterministic ordering.
4. Build all records/chunks in memory, validate schemas and cross-links, enforce
   budgets/metrics/global uniqueness, then return one frozen success result.
5. On any failure, return one sanitized failed result with no records/chunks and
   no filesystem/network/export/checkpoint/raw-store side effect.

## Files and bounded tests

Expected production changes:

- `requirements.txt` exact tree-sitter pins.
- New domain models/rules/port/infrastructure adapter and
  `foundation/application/use_cases/build_git_symbols.py` with package exports.
- No modification to M9-B behavior except additive shared helpers if required.
- Stage artifacts under `.codex-workflow/20260805-m9c/`.

Focused tests must cover:

- Exact schema fields and all symbol types, nullable fields, and additional
  property rejection.
- C++/Java fixtures for namespaces/packages, nested classes, class/struct/
  interface/enum, functions/methods/constructors, comments, templates,
  multiline signatures, overload IDs, and source-order determinism.
- Parse matrix above, Kotlin/XML policy, parser hard failures, malformed spans,
  and no partial output.
- Exact prefix, class-body exclusion, method-body inclusion, token counts,
  normalization, complete-line splitting, overlap/part metadata, unsplittable
  lines, chunk preimages, duplicate IDs, true collision rejection, and symbol
  linkage.
- Public adversarial boundaries (`object()`, `None`, wrong enums, missing/extra
  fields, forged frozen objects, impossible counters, wrong profile/tokenizer,
  wrong commit/path) plus zero-call/zero-side-effect assertions.
- Existing M9-B focused suite, M9-A regression, M8-D/E regression, architecture
  checks, `python -m compileall -q src tests`, and scoped `git diff --check`.

## Acceptance gate

Independent review must be run in a fresh session and must report `VERDICT: PASS`
with no unresolved P0-P3 findings. Only then update `.local_ai/ROADMAP.md` and
`.local_ai/IMPLEMENTATION_STATE.md`, commit, and push `codex/m8-m9`.
