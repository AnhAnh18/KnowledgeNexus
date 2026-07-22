# M6D-D consolidated implementation contract

Base: `9b4fec070187e373bac7de7e07560a6cf8dc7b0d` (approved M6D-C head).

This document replaces the original M6D-D prompt and all incremental
amendments. It is the single implementation reading for this worktree.

## Boundary

Convert one validated Confluence `CanonicalDocument` and its immutable M6D-C
`WikiDocumentStructure` into an ordered tuple of schema-valid `ChunkRecord`
dictionaries plus deterministic JSON-compatible metrics. Inject the validated
`ChunkingProfile`, `TokenizerPort`, existing ID/record helpers, and schema
validator. Domain/application code performs no profile loading, asset loading,
filesystem I/O, network I/O, persistence, embedding, relation extraction, ACL
resolution, media processing, or export.

## Assembly and identity

- Process the complete section stream in source order. Join contiguous prose
  blocks in a section with one blank line; tables and code remain isolated
  authoritative M6D-C blocks and are never reparsed.
- An explicitly headed section with no normalized prose, table, or code emits
  nothing and increments `empty_sections_skipped`.
- Require a schema-valid `confluence`/`wiki_page` canonical document whose
  non-null string title exactly equals `structure.page_title`. Use its
  `document_id` directly as both record identity and the chunk-ID stable key.
- Map title, space key, page ID, source version, and updated time. Emit
  `language="unknown"`, `acl_tags=["restricted:unresolved"]`, empty Jira and
  relation lists. Wiki-inapplicable optional fields are omitted by passing
  `None`. Do not add global chunk indexes.

## Exact budget text

Every decision uses the exact emitted text: body/wrapper, breadcrumb joined by
U+203A, one blank line, then `TextNormalizationRules.normalize_text`; tokenize
that exact value again for the decision, ID, record text, and count. Breadcrumb
is excluded only from overlap content and counts in every final budget. All
budgets come from the injected profile; `target_tokens` is soft and
`hard_maximum_tokens` is absolute.

## Short-section merge

Only explicitly headed prose-only sections at level 2 or 3 may merge. Both
sections must be source-adjacent, have the same heading level and the same
immediate parent identity. Derive parents before dropping empty sections with
a structural level stack over source ordinals: pop levels greater than or equal
to the current level and use the nearest remaining lower-level source ordinal,
or a document-root sentinel. The root sentinel is valid for root-level h2/h3.
Preambles and h1 never merge. A section containing prose plus table/code is not
prose-only. The first section keeps its breadcrumb; each absorbed section is
introduced by `"#" * heading_level + " " + heading_path[-1]`. Merge greedily
while below the profile minimum and the exact trial fits the hard maximum.

## Forced splitting

- Prose is split only when its exact unsplit emitted text exceeds the hard
  maximum. Use paragraph, sentence, line, then tokenizer-character-offset
  boundaries. Sentence endings for 1.2.0 are `. ! ? 。 ！ ？` followed by
  whitespace/end. Preserve source slices, re-tokenize every trial, support
  overlapping tokenizer spans, guarantee character progress, and never decode.
- Pack the longest source-ordered prefix fitting the target. If the first
  indivisible unit exceeds target but fits hard maximum, emit it. Later windows
  add at least one new unit. Forced prose windows take the largest previous-body
  suffix within `overlap_tokens`, using the same boundary priority and reducing
  it as required by the next exact hard budget. Internal non-overlap source
  ranges are contiguous, gap-free, and cover the candidate exactly.
- Split oversize code by complete original lines, reconstructing the original
  fence marker and info string. Enforce target, hard maximum, total max lines
  including overlap, and overlap lines. Never split/truncate a line.
- Split oversize tables by original rows, repeating exact header and separator,
  with no overlap and no row splitting.

## IDs, parts, validation, metrics

Unit keys are: breadcrumb; split prose `#w{part}`; table `#table{ordinal}` and
split table `#g{part}`; code `#code{ordinal}` for atomic and split parts. Table
and code ordinals are zero-based per section and count only the same kind.
Atomic records omit part fields; split units use zero-based `part_index` and a
shared positive `part_total`. Code parts deliberately share the code unit key;
their normalized text distinguishes their ID preimages.

Retain the full ID preimage. The first base ID is unchanged; a byte-identical
preimage repeated later receives stable `-1`, `-2`, ... suffixes. The same base
ID from a different preimage is `chunk_id_collision`. Validate every record.

Required metrics are `chunks_total`, `chunks_by_kind`,
`chunks_over_hard_max`, `sections_merged`, `oversize_splits`,
`empty_sections_skipped`, `token_count_p50`, and `token_count_p95`; additional
split/overlap/fallback counters may be included. Percentiles follow
CHUNKING_SPEC section 9's integer nearest-rank formula.

Sanitized categories include `canonical_document_validation_failed`,
`document_structure_identity_mismatch`, `breadcrumb_over_hard_max`,
`unsplittable_prose_fragment`, `unsplittable_code_line`,
`unsplittable_table_header`, `unsplittable_table_row`,
`chunk_budget_violation`, `chunk_id_collision`,
`chunk_record_validation_failed`, and `chunking_failed`. Exceptions expose no
content, identity, path, hash, or URL.

## Acceptance and workflow

Add an offline composition CLI with explicit `--page-id`, `--raw-root`,
`--profile-path`, `--tokenizer-assets-dir`, and `--crawled-at`. It runs
M6A raw -> M6C -> M6D-C -> M6D-D twice, creates no files and network calls, and
prints aggregate sanitized JSON only. Asset-backed tests must use the exact
pinned external bundle and must not skip. Stop with a working-tree review
notice and proposed green lettered stack; do not commit M6D-D before owner
authorization.
