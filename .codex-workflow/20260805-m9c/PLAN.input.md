# M9-C Minimal Symbol Index - Initial Plan

## Objective

Activate the bounded C++/Java symbol-index seam over the authority observations
produced by M9-B. Emit schema-valid `SymbolRecord` dictionaries and deterministic
`code_symbol` chunks linked by `chunk_id`, while preserving M9-B's atomic,
commit-bound, no-fallback behavior for authority files.

## Normative inputs

- `contracts/foundation/decision_logs/AI_Knowledge_Platform_Master_Spec_v7_1.md` §12.1-12.2.
- `contracts/foundation/CHUNKING_SPEC.md` §§5.1-5.4 and §7.
- `contracts/foundation/schemas/symbol_record.schema.json` and referenced defs.
- Active chunking profile and `ChunkRecord` schema.
- M9-B `GitRepositorySnapshot`/`CodeDocumentPlan` authority observations and
  commit/branch/path provenance.

## Bounded scope

1. Add immutable, runtime-validated symbol observation/result models. A symbol
   observation carries parser language/type/name/qualified name/signature,
   commit-valid one-based line range, parent, attached leading comment, and
   parse status. Results are atomic: success has records/chunks and no error;
   failure has one sanitized category and no partial records.
2. Add a parser capability port and a tree-sitter adapter for the agreed MVP
   languages C++ and Java. Use official grammar packages and pin compatible
   versions in the dependency manifest. No regex/ad-hoc parser fallback is
   permitted. Kotlin/XML remain symbol-less and continue using M9-B fallback
   behavior.
3. Add `SymbolIdGenerator` using
   `{repo}:{branch}:{file_path}:{qualified_name}`, adding
   `~sha256(signature)[:8]` only for deterministic same-qualified-name
   overloads. Preserve stable source ordering and parent links.
4. Add `SymbolRecordBuilder` producing plain JSON-compatible dictionaries,
   schema-validating them before return, including exact commit hash, language,
   parse status, and `scanned_at`. `chunk_id` is required for emitted symbols
   and must link to an emitted `code_symbol` chunk.
5. Build symbol chunks from complete source lines with the contract provenance
   prefix and attached doc-comment. Class/struct/interface/enum chunks include
   declaration/member signatures but exclude method bodies. Methods/functions
   use their full declaration/body unless oversized; oversized symbols split by
   complete lines under the active tokenizer/profile limits with `#p{n}` IDs and
   contiguous part metadata. A single unsplittable line fails closed.
6. Integrate M9-C into the M9-B code-document use case only for authority
   observations. Non-authority files keep `code_window` chunks; authority files
   with parser errors may produce `parse_status=partial` plus the bounded
   symbol/fallback policy defined by the normative contract, but never silently
   fall back or emit partial success outside the approved policy.
7. Enforce deterministic ordering, global chunk-ID uniqueness, source line-range
   bounds, symbol/chunk linkage, profile identity, and cross-field counters.
   Validate forged objects and malformed runtime inputs at every public boundary.

## Explicit non-goals

- No call graph, references, fields/variables, template instantiations, symbol
  retrieval, embedding, Qdrant/indexing writes, export publication, network,
  checkpoint, raw-store, ACL, or delta/tombstone behavior.
- No Kotlin/XML symbol extraction and no regex fallback in place of tree-sitter.
- No broad repository scan or full M10 snapshot.

## Files expected to change

- `requirements.txt` (pinned tree-sitter runtime and official C++/Java grammars).
- New foundation domain model/rule/port/adapter/use-case modules under the
  existing package layout, with package exports.
- Focused M9-C tests plus architecture boundary coverage.
- Stage artifacts under `.codex-workflow/20260805-m9c/` only.

## Validation and acceptance

- Focused model, generator, builder, parser, chunker, and use-case tests.
- Adversarial negative pass: `object()`, `None`, wrong enum values, missing or
  extra fields, forged/frozen-object bypasses, invalid line ranges, impossible
  counters, duplicate overloads/IDs, malformed parser results, and wrong
  commit/path provenance all fail closed without side effects.
- Schema validation for every SymbolRecord and ChunkRecord.
- Determinism: same snapshot and timestamp produce byte-identical records,
  chunks, ordering, and digest; overload suffixes are stable.
- Regression: M9-B focused suite, M9-A regression, M8-D/E regression, compileall,
  and scoped `git diff --check`.
- Independent review in a fresh session; fix every P0-P3 finding before ledger
  update and commit/push.

## Risks/decisions for review

- Tree-sitter package/API compatibility and grammar version pinning.
- Exact node mappings and qualified-name construction for C++ templates,
  namespaces, nested classes, Java packages/classes/methods, and overloaded
  methods.
- How partial/error trees map to the normative `parse_status` without creating
  an unauthorized fallback stream.
- Tokenizer/profile access for symbol chunks while keeping M9-B atomicity.
