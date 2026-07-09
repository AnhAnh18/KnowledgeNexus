# CHUNKING_SPEC.md

Chunking specification for the AI Knowledge Platform — Part 1 (Knowledge Foundation).

| Field | Value |
|---|---|
| Status | Normative |
| chunker_version | 1.1.0 |
| Embedding model (selected by Task 2) | `sentence-transformers/all-MiniLM-L6-v2` — 256 word-piece limit, silent truncation |
| Applies to | ChunkRecord (`schemas/chunk_record.schema.json`) |
| Parent spec | AI_Knowledge_Platform_Master_Spec_v7_1.md §16.3 |
| Scope | Confluence wiki pages and Git source files under the POC scope (SVMC/938880621, spensdk). No embedding, no retrieval — that is Task 2/Task 3. |

This document is authoritative for how `chunks.jsonl` is produced. Where this file and the master spec appear to disagree, the master spec's §16.3 invariants win and this file must be corrected.

---


## 0.1 Migration status *(v7.3)*

BGE-M3 migration is recorded in `AI_Knowledge_Platform_v7_3_Update.md`. The BGE-M3 chunk budget is under benchmark and will be promoted only when `chunker_version` 1.2.0 is locked. Until then, §1 below remains the last normative locked profile (all-MiniLM-L6-v2, chunker_version 1.1.0). Do not treat any BGE-M3 number as normative until 1.2.0 is stamped here.

## 1. Tokenizer and Budget

Chunk size is measured in tokens counted with the **embedding model's own tokenizer**, not `tiktoken`. Task 2 has selected **`sentence-transformers/all-MiniLM-L6-v2`**, which uses the BERT uncased **WordPiece** tokenizer (30,522-token vocab) and **truncates input to 256 word pieces, silently**. Budgeting in that exact tokenizer is what makes `token_count` map onto the model's real truncation limit; counting in a different tokenizer (e.g. `cl100k_base`) would under-count, and code especially would silently lose its tail at embed time. `chunker_version` 1.1.0 reflects this model-tuned configuration (§7).

Sizes stay safely under the 256-WP ceiling (leaving room for the `[CLS]`/`[SEP]` tokens the model adds) and small enough for good retrieval — with this model, shorter chunks that fully fit retrieve *better* than long chunks that get truncated.

| Parameter | Value (WordPiece) | Meaning |
|---|---|---|
| `target_tokens` | 200 | Preferred chunk size. The packer aims here. |
| `min_tokens` | 64 | Chunks smaller than this are merged forward where the algorithm allows. |
| `hard_max_tokens` | 240 | A chunk MUST NOT exceed this. 240 + 2 special tokens = 242 ≤ the model's 256 limit, so nothing is silently truncated. Larger units are force-split. |
| `overlap_tokens` | 40 | Applied **only** to forced splits of an oversize unit (§4.4, §5.3). Non-split adjacent chunks do not overlap. |
| `code_window_target_tokens` | 200 | Token target for symbol-less/oversize code windows (§5). Windows are packed by tokens, not a fixed line count. |
| `code_window_max_lines` | 40 | Secondary guard so a token-packed window never spans an unreadable number of lines. |
| `code_window_overlap_lines` | 4 | Line overlap between consecutive code windows. |

`min_tokens` is a merge *hint*, not an invariant: a standalone short section with no valid merge target (e.g. a lone heading followed immediately by a subheading) may be emitted below `min_tokens`. `hard_max_tokens` is an invariant: the quality report MUST report `chunks_over_hard_max = 0`.

> **Model coupling and model-specific limits.** These numbers are tuned to all-MiniLM-L6-v2's 256-WP limit. Changing the embedding model to one with a different context window (e.g. a 512-WP or 8k model) is a chunker-configuration change: bump `chunker_version` and re-export as a `full_snapshot` (`config_invalidated`, master spec §16.2). Two further properties of this specific model bear on Task 2 (not on chunk sizing): it is **English-only** — Korean/Vietnamese wiki text will embed poorly, so a multilingual model should be considered if the corpus is not English; and it was **not trained on source code** — code retrieval quality will be weak regardless of how code is chunked, so a code-aware embedding model would serve the code chunks far better.

---

## 2. Text Normalization (applied before hashing and token counting)

All chunk text is normalized identically so that `chunk_id` is stable and `token_count` is reproducible:

1. Unicode NFC normalization.
2. Line endings → `\n` (CRLF and CR collapsed to LF).
3. Trailing whitespace stripped from each line.
4. Runs of 3+ blank lines collapsed to exactly one blank line.
5. Leading/trailing blank lines of the chunk removed.

Normalization is applied to the *assembled* chunk text (breadcrumb/comment prefix line included, see below), and that normalized string is what goes into both the token count and the `chunk_id` hash and the `text` field. There is exactly one normalized form per chunk; no un-normalized text is ever emitted.

---

## 3. chunk_id and Stability

```
US = "\x1f"   # ASCII unit separator, never appears in the inputs
chunk_id = "chunk:" + source_system + ":" + sha256(document_stable_key + US + unit_key + US + normalized_text)[:16]
```

If two chunks in one export produce a byte-identical hash (genuinely duplicated content), append `-1`, `-2`, … in stable document order to disambiguate.

**`document_stable_key`** (identity of the source document, deliberately excluding volatile provenance):

| Source | document_stable_key |
|---|---|
| Confluence | `confluence:page:{page_id}` |
| Git | `git:{repo}:{file_path}` |

Branch and commit hash are **not** part of `document_stable_key` or `chunk_id`; they are carried as ChunkRecord fields (`branch`, and the document's `source_version`). Unchanged content therefore keeps its `chunk_id` across syncs, so Task 2 can skip re-embedding it (master spec §16.3, invariant 1).

**`unit_key`** (identity of the unit within the document; a disambiguator, since `normalized_text` already dominates the hash):

| content_kind | unit_key |
|---|---|
| `prose` | breadcrumb path, e.g. `ObjectManager Design Note › Locking Strategy` |
| `prose` (oversize split) | breadcrumb + `#w{n}` where n is the 0-based window index |
| `table` | breadcrumb + `#table{ordinal}` (ordinal = position among tables in that section) |
| `table` (row-group split) | breadcrumb + `#table{ordinal}#g{n}` |
| `code_block` | breadcrumb + `#code{ordinal}` |
| `code_symbol` | `qualified_name` (overloads: `qualified_name~{sha256(signature)[:8]}`) |
| `code_symbol` (oversize split) | `qualified_name` + `#p{n}` |
| `code_window` | `file_path` + `#w{n}` |

Consequence to keep in mind: editing one section or symbol changes only that unit's `normalized_text` (and possibly its window split), so its neighbours keep their IDs. Editing tokens *above* a `code_window` shifts window boundaries and will re-chunk the tail of that file — this is the accepted limitation for symbol-less files (§5.4).

---

## 4. Wiki Chunking (Confluence pages)

Input is the normalized Markdown produced by the connector, **after** the macro policy in master spec §10.1 has been applied (code fences materialized, `jira`/`drawio`/`include` handled, `toc` dropped, unknown-macro text inlined). Media and unresolved includes are already inline placeholders such as `[media: diagram.png]` and are treated as ordinary text.

### 4.1 Sectioning

- Split the page on headings **h1–h3**. Each such heading starts a new section that runs until the next h1–h3 heading.
- Headings **h4 and deeper** do **not** start new chunks; they remain inline as text inside the current section.
- `heading_path` is the ordered list of ancestor headings for the section, always starting with the page title. Example: `["ObjectManager Design Note", "Locking Strategy"]`.

### 4.2 Breadcrumb Prefix

The first line of every wiki chunk's `text` is the breadcrumb, the `heading_path` joined with ` › ` (U+203A), followed by a blank line, then the section body:

```
ObjectManager Design Note › Locking Strategy

<body text…>
```

The breadcrumb is part of the normalized text: it is counted in `token_count` and included in the `chunk_id` hash. It gives each chunk standalone context without a separate metadata read.

### 4.3 Packing and Merging

- If a section body is `≤ hard_max_tokens`, it is emitted as a single `prose` chunk (breadcrumb + body).
- If a section is `< min_tokens`, merge it **forward** into the next sibling section under the same parent, concatenating bodies under the deeper/again-stated breadcrumb, until the merged chunk reaches `min_tokens` or the parent's sections are exhausted. Never merge across an h1 boundary. Track `sections_merged`.
- A section that cannot reach `min_tokens` and has no valid forward target is emitted as-is (small chunk allowed).

### 4.4 Oversize Prose Sections

If a section body exceeds `hard_max_tokens`, split it into windows at **paragraph boundaries** (blank-line separated blocks), packing paragraphs toward `target_tokens` and never exceeding `hard_max_tokens`:

- Consecutive windows carry `overlap_tokens` (40) of trailing text from the previous window, taken at a paragraph or sentence boundary — never mid-line.
- A window **never splits a fenced code block or a table row** (§4.5, §4.6). If a single fenced block or table alone exceeds `hard_max_tokens`, it becomes its own chunk handled by §4.5 / §4.6 rather than by prose windowing.
- Each window is its own chunk with `content_kind: prose`, `part_index` (0-based) and `part_total` set. The breadcrumb prefix is repeated on every window.

### 4.5 Fenced Code Blocks Inside Pages

- A fenced code block (from a Confluence `code` macro or literal fence) that fits within `hard_max_tokens` becomes one chunk with `content_kind: code_block`, breadcrumb prefixed, language tag preserved in the body.
- If it exceeds `hard_max_tokens`, split into token-packed line windows (accumulate lines up to `code_window_target_tokens`, never exceeding `hard_max_tokens` or `code_window_max_lines`, with `code_window_overlap_lines` overlap), each part `content_kind: code_block`, with `part_index`/`part_total`.
- Small code blocks may remain inline inside the surrounding `prose` chunk if they were already part of a section body under `target_tokens`; they are only pulled out when the section is oversize and windowing would otherwise cut them.

### 4.6 Tables

- A Markdown table that fits within `hard_max_tokens` is emitted atomically as one `content_kind: table` chunk (breadcrumb prefixed).
- A larger table is split into **row-groups**, each group repeating the header row and the alignment row so every chunk is a valid, self-describing table. `part_index`/`part_total` set; `content_kind: table`. A table row is never split across chunks.

---

## 5. Code Chunking (Git source files)

Applies to files scanned by the Git connector. Symbol boundaries come from the tree-sitter symbol indexer (master spec §12.1: C++ and Java in MVP). Kotlin and XML have no symbols in MVP and use the fallback in §5.4.

### 5.1 Symbol Chunks

- Emit **one chunk per top-level extractable symbol**: `function`, `method`, `class`/`struct`/`interface`/`enum` declaration, `namespace`/`package` where meaningful.
- A symbol chunk includes the symbol's **leading doc-comment / attached comment block** immediately above it.
- A `class`/`struct`/`interface` chunk contains the declaration and member signatures **but not the full bodies of its methods** — each method is its own chunk. This keeps class chunks small and avoids duplicating method text.
- `content_kind: code_symbol`. Fields `symbol`, `line_start`, `line_end`, `file_path`, `repo`, `branch` are populated; the chunk links to its SymbolRecord via matching `symbol`/`chunk_id`.

### 5.2 Path/Symbol Prefix

The first line of every code chunk's `text` is a comment giving provenance, followed by a blank line, then the code:

```
// spensdk · src/native/ObjectManager.cpp · ObjectManager::Release

void ObjectManager::Release(Object* obj) {
    …
}
```

The prefix comment is part of the normalized text (counted and hashed), using the file's line-comment token (`//` for C++/Java/Kotlin, `<!-- -->` for XML windows).

### 5.3 Oversize Symbols

A single function/method whose body exceeds `hard_max_tokens` is split into token-packed line windows (packed to `code_window_target_tokens`, capped at `hard_max_tokens` and `code_window_max_lines`, with `code_window_overlap_lines` overlap), `content_kind: code_symbol`, `part_index`/`part_total` set, prefix comment repeated. Splitting is by line only; it does not attempt to parse sub-blocks. Note that code tokenizes to many more word pieces than prose, so a single method often exceeds 240 WP and will be split into several parts — this is expected.

### 5.4 Symbol-less Files and Fallback Windows

- Files with no extractable symbols (XML, Kotlin in MVP, or a C++ file that produced only ERROR nodes) are chunked into token-packed line windows (accumulate lines up to `code_window_target_tokens`, never exceeding `hard_max_tokens` or `code_window_max_lines`, with `code_window_overlap_lines` overlap). `content_kind: code_window`; `symbol` is null; `line_start`/`line_end` and `part_index`/`part_total` are set.
- A short **file preamble** (license header, includes) below `min_tokens` is merged forward into the first following chunk rather than emitted alone.

---

## 6. content_kind Enumeration

`content_kind` is a required ChunkRecord field. Allowed values (mirrored in `schemas/defs.schema.json`):

| Value | Produced by |
|---|---|
| `prose` | Wiki heading-section text (§4) |
| `table` | Wiki table chunk, atomic or row-group (§4.6) |
| `code_block` | Fenced code block extracted from a wiki page (§4.5) |
| `code_symbol` | Code chunk built around one symbol (§5.1, §5.3) |
| `code_window` | Fixed line-window chunk for symbol-less files or oversize splits (§5.4) |

---

## 7. Update Behavior

Chunking participates in incremental sync as defined in master spec §18.3. Restated for the chunker:

1. **Document short-circuit.** If the document's `content_hash` and the active `chunker_version` are both unchanged since the last export, emit nothing for that document.
2. **Re-chunk and diff.** Otherwise, re-chunk the document, then compare the new set of `chunk_id`s against the previously exported set for that `document_stable_key`:
   - `chunk_id` present in both → unchanged; **not re-emitted** in a `delta` export.
   - `chunk_id` new → emitted.
   - `chunk_id` absent from the new set → **tombstoned** with reason `content_updated` (master spec §16.2).
3. **chunker_version stamped.** Every ChunkRecord carries `chunker_version`; `manifest.json` carries the `chunker_version` used for the run. A change to `chunker_version` invalidates all chunks (`config_invalidated`) and forces a `full_snapshot` (master spec §16.1, §16.2). Version history: `1.0.0` used a model-agnostic `cl100k_base` budget (target 450 / hard max 1000); `1.1.0` tunes the budget to the selected embedding model all-MiniLM-L6-v2 (WordPiece, target 200 / hard max 240; §1). Selecting a different embedding model later is itself such a change.
4. **ACL-only change.** If page content is identical but restrictions changed, the same `chunk_id`s are re-emitted with updated `acl_tags` — no tombstones (master spec §18.3).

---

## 8. Determinism (invariant)

Given identical inputs (same normalized document bytes) and identical chunker configuration (this spec's parameters + `chunker_version`), the chunker MUST produce a **byte-identical** `chunks.jsonl`: same chunks, same `chunk_id`s, same order, same field values. No wall-clock time, map/set iteration order, or locale may influence output. Document order and within-document unit order are fixed by source position. This is verified by acceptance criterion "Chunk stability" (master spec §19).

---

## 9. Quality Report Counters

The chunking stage contributes the following to `quality_report.md`:

| Counter | Meaning |
|---|---|
| `chunks_total` | Total chunks emitted this run. |
| `chunks_by_kind{content_kind}` | Count per `content_kind`. |
| `chunks_over_hard_max` | MUST be 0 (invariant check). |
| `sections_merged` | Wiki sections merged forward for being under `min_tokens` (§4.3). |
| `oversize_splits` | Units force-split for exceeding `hard_max_tokens` (§4.4, §4.5, §4.6, §5.3). |
| `fallback_window_files` | Files chunked by the symbol-less fallback (§5.4). |
| `empty_sections_skipped` | Heading sections whose normalized body was empty. |
| `token_count_p50` / `token_count_p95` | Chunk token-count distribution, for tuning against `target_tokens`. |

---

## 10. Open Items (tracked in master spec §20.3)

- Token budget is **resolved**: tuned to the selected model all-MiniLM-L6-v2 (target 200 / hard max 240 / overlap 40 WordPiece; §1). Revisit only if the embedding model changes (→ `chunker_version` bump + `full_snapshot`).
- Model fit: all-MiniLM-L6-v2 is English-only and not code-trained. If wiki content is substantially Korean/Vietnamese, or code retrieval quality proves insufficient, Task 2 should evaluate a multilingual and/or code-aware model. That changes Task 2 config (and possibly `chunker_version`), not the Part 1 record shapes.
- `ChunkRecord.language` detection method is unspecified; MVP may emit `"unknown"`. Decide detector and whether it is per-chunk or per-document.
- Kotlin symbol extraction (would move `.kt` files from §5.4 fallback to §5.1 symbol chunks) is deferred to Phase 1.5.
