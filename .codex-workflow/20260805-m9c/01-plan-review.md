# M9-C Plan Critique

RECOMMENDED_IMPLEMENTATION_PROFILE: complex

The plan has the right high-level direction (tree-sitter C++/Java, no regex fallback, schema validation, and adversarial tests), but it is not yet actionable against the existing M9-B seam. The parser, symbol chunking, and authority-result semantics need an explicit contract matrix before implementation.

## Findings

### P1 - The plan does not define the M9-B authority-plan migration

The current `CodeDocumentPlan`/`GitRepositorySnapshot` invariants require `included_chunk_count == 0` in a snapshot, reject any authority document that has chunks, and require every emitted chunk to be `content_kind=code_window` whose text is the entire assembled source window. M9-C's stated requirement to emit authority `code_symbol` chunks therefore cannot work by adding a parser module alone. The revised plan must name the model/use-case changes (including metrics, chunk validation, authority observation linkage, and result failure categories), preserve atomic failure semantics, and specify which existing invariants are replaced versus retained. Add a migration test proving a mixed snapshot (authority symbols plus non-authority fallback windows) is valid and that a failed authority parse returns no partial plan.

### P1 - Chunk-ID generation is underspecified and risks violating CHUNKING_SPEC §3

The plan specifies `SymbolIdGenerator`, but does not specify the `ChunkRecord.chunk_id` preimage. For Git symbol chunks the contract is `chunk:git:` plus SHA-256 of `git:{repo}:{file_path}` + unit key + normalized text; branch and commit must not enter that ID. Symbol IDs do include branch and use the overload suffix only for same-qualified-name overloads. The implementation plan must distinguish these two IDs, define duplicate byte-identical chunk handling (`-1`, `-2`) versus hash-collision failure, and add a test showing unchanged symbol text keeps its chunk ID across branch/commit changes while symbol IDs follow §12.2.

### P1 - Parse-status and fallback behavior is ambiguous

Master §12.1 requires C++ files with ERROR nodes to be recorded as `parse_status: partial` and extraction must not abort. CHUNKING §5.4 allows fallback windows only for symbol-less files (including a C++ file producing only ERROR nodes). The plan says “partial plus the bounded symbol/fallback policy” without defining the policy for: clean symbols; partial trees with some symbols; partial trees with zero symbols; parser hard failure; and unsupported Kotlin/XML. This is a correctness and security boundary because an unauthorized fallback stream could duplicate or expose source unexpectedly. Add a table of input state -> status -> SymbolRecords -> chunks -> failure category. The minimum contract should explicitly say whether partial-symbol files emit only successfully extracted symbols, and whether only the zero-symbol/ERROR-only case emits `code_window` chunks.

### P1 - Chunk-record requirements are not carried through the plan

The plan mentions linkage and profile limits but omits the complete `ChunkRecord` field/semantic contract: `acl_tags`, `content_hash`, `chunker_version`, `source_version`, `document_id`, empty arrays, language, line/part metadata, and exact schema field set. It also does not state that the assembled prefix/comment is normalized before hashing and token counting, or that the exact pinned BGE-M3 tokenizer asset must be used. Existing M9-B plan validation currently requires all optional fields to be materialized and checks source reconstruction. The revised plan must define the symbol-chunk builder inputs/outputs and cross-checks, including `chunk_id` -> SymbolRecord linkage, source commit/path identity, line bounds, contiguous parts, and `chunks_over_hard_max == 0`.

### P1 - Symbol extraction and naming rules are not sufficiently deterministic

The plan lists qualified names and parents but does not define node-to-symbol mappings or ordering for C++ namespaces, nested classes, templates, Java packages/classes/methods, constructors, operators, anonymous/nested declarations, or declarations split across lines. It also does not say how a class chunk obtains declaration/member signatures while excluding method bodies, or how attached leading comments are selected when comments are separated by annotations/preprocessor lines. These choices directly affect IDs and retrieval text. Add a deterministic mapping table, parent-stack algorithm, source-order tie-breakers, signature canonicalization, and fixture assertions for every MVP symbol type in §12.1 (including namespace/package).

### P2 - Oversize/class rendering and line-range semantics need an explicit algorithm

CHUNKING §5.1/§5.3 requires class/struct/interface/enum chunks to contain declaration and member signatures but not method bodies, while method/function chunks contain the full declaration/body and split only on complete lines. A class chunk is therefore not necessarily a contiguous source slice, yet the plan only says “build from complete source lines” and “include signatures.” Specify the rendered text algorithm, whether comments are included once or per part, how `line_start`/`line_end` refer back to source, and how gaps/overlaps are validated. Include tests for a class with two methods, a multiline signature, and an unsplittable over-budget line.

### P2 - Dependency/API pinning is not acceptance-testable

“Pin compatible versions” is not a concrete dependency requirement. `tree-sitter` and the official grammar packages have incompatible API combinations across releases. Name exact package/version pins, parser construction API, grammar ABI compatibility, and a smoke test that parses C++ and Java without network/cache fallback. Add an architecture test that the application imports only the parser port and the tree-sitter adapter is the sole infrastructure dependency; retain the M9-B boundary checks.

### P2 - Atomic result validation needs a concrete public contract

The plan proposes immutable observation/result models but does not define their fields, status enum, or impossible combinations. In particular, a success must have records/chunks and no error, a failed result must have exactly one sanitized category and no records, and `partial` is a parse status—not an application failure status. Specify runtime checks before field access for `object()`, `None`, forged dataclass instances, wrong enum values, extra/missing fields, malformed parser node spans, duplicate symbols, and mismatched counts. Add tests that prove the repository reader/parser/chunker are not called after invalid request/dependency input and no partial plan escapes on any exception.

### P2 - Determinism/scanned-at source is not pinned

The plan requires byte-identical output “with the same snapshot and timestamp” but never states where `scanned_at` comes from. It must be an explicit request/config timestamp (not wall clock), normalized to RFC3339 UTC, and reused for every SymbolRecord in a run. Define stable record/chunk ordering and JSON serialization, and test repeated runs plus changed timestamps (records may change only in the timestamp field; chunk IDs/text must not).

### P3 - Extension/authority policy should be named, not inferred

M9-B currently derives authority from the fixed C++/Java extension set and maps many other extensions to language tags. The plan should explicitly preserve that policy: Kotlin/XML remain non-symbol fallback; unsupported or parser-ineligible files do not become authority by parser guesswork. Add tests for `.cc/.cpp/.h/.hpp/.java`, Kotlin/XML, case variants, and a path whose extension is unknown.

## Required acceptance tests

1. Schema tests validate every emitted SymbolRecord and ChunkRecord with `additionalProperties: false`, including nullable `signature`, `parent_symbol`, and `chunk_id` cases and all required chunk fields.
2. Parser fixtures cover C++/Java class, struct, interface, enum, function, method, namespace/package, nested parents, leading comments, multiline signatures, templates, and overloads; assert exact symbol IDs, suffixes, line ranges, parent links, source order, and parse status.
3. Parse-state matrix tests cover `ok`, `partial` with symbols, `partial` with zero symbols/ERROR-only, hard parser failure, and Kotlin/XML fallback; assert no unauthorized fallback and no partial application result.
4. Chunk tests assert exact provenance prefix, NFC/newline/trailing-space normalization, BGE-M3 token counts, class-body exclusion, method-body inclusion, complete-line split/overlap limits, `#p{n}` IDs, unsplittable-line failure, source line bounds, and symbol/chunk linkage.
5. ID/determinism tests assert the CHUNKING_SPEC Git preimage (branch/commit excluded), duplicate identical chunks receive stable `-1/-2`, true hash collisions fail closed, and repeated runs produce byte-identical sorted output.
6. M9-B seam tests assert mixed authority/non-authority documents, updated counters and plan invariants, exact commit/branch/path provenance, and unchanged behavior for non-authority fallback windows.
7. Adversarial boundary tests use `object()`, `None`, wrong enum values, missing/extra fields, forged frozen objects, malformed parser results/spans, duplicate IDs, impossible status/count combinations, wrong tokenizer/profile, and invalid commit/path. Verify fail-closed sanitized categories and zero side effects.
8. Run the focused M9-C suite, existing M9-B/M9-A/M8-D/E suites, architecture checks, `compileall`, and `git diff --check`; record exact commands/results in the implementation report.

## Bounded alternatives

- **Seam shape (recommended):** extend `CodeDocumentPlan` with a validated `symbols` collection and symbol-chunk allowance, while retaining one atomic `GitCodeBuildResult`; add a dedicated symbol-index domain service behind the existing use case. This keeps one repository snapshot and one commit-bound transaction.
- **Seam shape (bounded alternative):** keep M9-B's plan immutable and add a second `BuildGitSymbols` application use case consuming only authority observations, then compose plans in a thin coordinator. This reduces changes to M9-B but requires a second cross-plan consistency/atomicity check before publication.
- **Partial parsing policy (recommended):** `partial` emits only successfully extracted symbols; emit `code_window` only when the parser yields no symbols and the file qualifies for §5.4. Do not invent fallback windows for unparsed regions unless the contract is amended.
- **Rendering policy (bounded alternative):** implement a source-preserving declaration assembler for aggregate symbols (declaration plus member signature spans) and source slices for methods/functions; document how non-contiguous aggregate spans map to one line range. A simpler contiguous class slice is contract-incompatible because it duplicates method bodies.

## Review conclusion

Revise the plan with the state matrix, ID algorithms, exact symbol mappings, complete ChunkRecord semantics, and explicit M9-B model migration before implementation. Until those are fixed, the plan is complex rather than a build-ready checklist.
