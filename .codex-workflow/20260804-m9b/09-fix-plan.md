# M9-B Re-review Fix Plan

## Scope

Address only the three findings in `07-review-2.md`. Do not broaden M9-B,
change schemas, alter Git source semantics, or modify M8/M9 ledger files before
validation and a fresh independent review pass.

## Fixes

1. Harden `CodeDocumentPlan` construction at its public model boundary.
   - Enforce the exact CanonicalDocument and ChunkRecord key sets and required
     schema version, source-system/source-type, repository, branch, commit,
     ACL, and path identities.
   - Recompute and verify document/chunk content hashes and stable IDs from the
     supplied values.
   - Require fallback `content_kind="code_window"`, active chunker profile,
     valid language/metadata, and chunk `file_path`/identity matching its
     owning document.
   - Preserve atomic rejection of duplicate IDs, impossible line/part
     counters, unsupported ownership, and metrics mismatches.
   - Test direct forged-plan construction (without the application), covering
     every semantic identity/hash/metadata field, exact emitted key sets,
     document-to-chunk ownership, authority observations, empty documents,
     duplicate/collision IDs, and metrics equality.

2. Harden tokenizer result validation in `BuildGitCodeDocuments`.
   - Require `start` and `end` offsets to be exact non-boolean integers before
     comparison or token counting.
   - Keep existing bounds, ordering, non-overlap, non-empty-text, and concrete
     `CharacterSpan`/`TokenizationResult` checks.
   - Reject bool, float, Decimal-like, missing, and raising offsets before any
     later tokenizer-derived work; prove malformed results cause no side effect
     and return only a sanitized failure.

3. Validate `LocalGitRepositoryReader` constructor dependencies.
   - Preserve `runner=None` as the default path, but reject falsey malformed
     runners, missing/non-callable `run`, and malformed injected seams
     synchronously without Git I/O. A callable runner's returned-result shape
     remains validated at the read boundary.

## Tests

Add focused adversarial tests for forged documents/chunks/plans, wrong hashes
and cross-field identities, float/bool/Decimal-like/missing tokenizer offsets,
no-side-effect malformed tokenizers, and malformed reader runners (including a
spy proving constructor validation performs no run). Retain all existing M9-B
tests and architecture boundary checks.

## Validation and review gate

Run the focused M9-B suite, M9-A regression, M8-D/E regression, compileall, and
scoped diff checks. Record exact commands in `10-fix-implementation.md`.
Launch a new independent review in a separate session. Do not update
`.local_ai/ROADMAP.md` or `.local_ai/IMPLEMENTATION_STATE.md` unless the fresh
review ends with `VERDICT: PASS`.
