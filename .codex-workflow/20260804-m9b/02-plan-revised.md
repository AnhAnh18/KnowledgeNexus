# M9-B Revised Plan: Pinned Local Git Code-Document Seam

## 1. Stage and non-goals

M9-B adds one bounded, read-only application seam for the local `spen-sdk`
repository. It reads source bytes from the caller-supplied full commit SHA,
builds schema-valid `CanonicalDocument` records, and emits only fallback
`code_window` `ChunkRecord`s for files that do not belong to the M9-C C++/Java
symbol-authority set.

This stage does not clone, fetch, contact a remote, mutate Git configuration,
write a raw store, checkpoint, export, embed, access Qdrant, parse symbols, or
emit `code_symbol` chunks. It does not change any Foundation schema or the
active `chunker_version`.

The implementation is atomic: a successful call returns one complete plan; any
later-file, tokenizer, schema, budget, or dependency failure returns only a
sanitized category and no documents, chunks, observations, or partial metrics.

## 2. Locked source identity and inputs

`GitSourceConfig` is a frozen, runtime-validated value with exactly these
fields:

- `clone_root`: absolute existing directory path whose final component is
  exactly `spen-sdk`; every component must be a non-reparse directory.
- `repo_name`: exactly `spen-sdk`.
- `branch`: exactly `develop`.
- `commit_sha`: exactly 40 lowercase hexadecimal characters.
- `crawled_at`: explicit timezone-aware RFC3339 string; no wall clock is read.
- `budgets`: a `GitScanBudgets` value (section 5).
- `case_policy`: the only accepted enum value,
  `reject_casefold_collisions`.

The reader verifies the requested branch and commit before reading a blob. The
stable identity is always `git:spen-sdk:{posix_file_path}` for both
`document_id` and `document_stable_key`; branch and commit are provenance only.
ACL values are exactly `acl_id=acl:repo:spen-sdk` and
`acl_tags=["repo:spen-sdk"]`.

## 3. Production components

Add the following bounded components and package exports only:

- `foundation/domain/models/git_code_source.py`: strict frozen models for
  config, budgets, file observations, metrics, snapshot, code-document plan,
  result, and sanitized error categories.
- `foundation/ports/git_repository_read_port.py`: a read-only port whose
  operation accepts `GitSourceConfig` and returns an exact
  `GitRepositorySnapshot`.
- `foundation/infrastructure/git/local_git_repository_reader.py`: the local
  Git adapter described in section 4.
- `foundation/application/use_cases/build_git_code_documents.py`: the atomic
  application composition described in section 9.
- Focused tests under domain, port/architecture, infrastructure, and
  application test paths. No unrelated production edits.

Every public/application constructor and operation rejects `None`,
`object()`, wrong enum/runtime types, forged result objects, missing required
fields, and forbidden extra fields before field access or I/O. Nested values
are defensively rebuilt into immutable tuples or JSON-safe copies.

## 4. Git command and commit binding

The adapter uses a private injected `GitCommandRunner` seam. The runner
accepts an immutable argv tuple, optional bytes stdin, a finite timeout, and a
finite stdout/stderr cap; it returns an exact immutable result containing
return code and bytes. It must reject shell execution and malformed results.

Each invocation uses an absolute Git executable and fixed environment values:

- `GIT_CONFIG_NOSYSTEM=1`;
- `GIT_CONFIG_GLOBAL` set to the platform null device;
- `GIT_TERMINAL_PROMPT=0`;
- `GIT_OPTIONAL_LOCKS=0`.

No command accepts a remote, URL, shell fragment, user-controlled option, or
environment override. Timeouts, non-zero exits, output overflow, decode
failures, and unexpected runner exceptions map to stable categories without
including argv, stderr, paths, or exception text. Per-command timeout is 10
seconds; stdout and stderr caps are 32 MiB and 64 KiB respectively.

The adapter performs only these operations:

1. `rev-parse --verify HEAD` and `symbolic-ref --short HEAD` in the validated
   local root; exact lowercase commit and exact branch are required.
2. `ls-tree -rz --full-tree {commit_sha} --` with bounded output. Parse only
   NUL-delimited records of the exact `mode type oid<TAB>path` form. The parser
   rejects malformed records, invalid UTF-8, duplicate paths, unsupported
   modes, and trailing non-NUL bytes. Repeated blob OIDs are allowed because
   different files may intentionally share one blob.
3. `cat-file --batch-check` first obtains bounded sizes for tree-provided blob
   object IDs, then one `cat-file --batch` request stream reads only candidate
   text blobs. Parse each exact header and byte count, rejecting missing,
   substituted, truncated, or extra bytes. Excluded blobs are accounted for by
   their checked size without loading their body.

All source bytes therefore come from the pinned commit object database, not
from worktree files. A dirty tracked file, concurrent worktree edit, ignored
file, symlink, or reparse redirect cannot change the bytes used for a result.
Tests must dirty a worktree file after the commit is pinned and prove the
snapshot remains commit-bound.

## 5. Path, tree-entry, exclusion, and budget policy

Git paths are decoded as strict UTF-8, normalized to NFC, and treated as
POSIX-relative paths. Reject an entry if it has a NUL/control character,
backslash, empty component, `.` or `..` component, leading/trailing slash,
Windows-reserved component (`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`,
`LPT1`-`LPT9`, case-insensitive), or a component ending in a dot or space.
Reject NFC-equivalent duplicates and casefold-equivalent duplicates under the
only supported case policy. Unsafe paths fail the whole scan before a blob is
read. POSIX separators remain `/` in every identity and record.

Tree entries with symlink mode or gitlink/submodule mode fail closed with
`unsupported_tree_entry`; they are never followed. Directories are traversed
by `ls-tree`; only regular blob entries are candidates.

`GitScanBudgets` has positive integer fields with exact relationships and
hard upper bounds:

- `max_tree_entries=100_000`;
- `max_file_bytes=4 MiB`;
- `max_total_raw_bytes=128 MiB`;
- `max_files=20_000`;
- `max_normalized_bytes=8 MiB` per file;
- `max_in_memory_bytes=256 MiB` aggregate owned source/record budget.

Callers may choose lower values but may not exceed these maxima. A tree-entry,
file-count, raw-byte, normalized-byte, or owned-memory breach fails atomically
with its category. Empty blobs are valid documents and produce zero chunks.
Raw byte counts are measured before UTF-8 decode; normalized byte counts are
UTF-8 bytes of the canonical normalized document text; chunk text is accounted
separately against the owned-memory budget.

The following path policies are deterministic and continue scanning while
incrementing the corresponding exclusion counter: generated components or
filenames `generated`, `gen`, `build`, `dist`, `out`, `target`, `node_modules`;
vendor components `vendor`, `third_party`, `external`, `Pods`; and the fixed
case-insensitive binary-extension set for images, archives, object/library/
executable files, fonts, and PDFs. A candidate text blob containing NUL is
classified as binary and excluded. Invalid UTF-8, unreadable/missing blobs,
unsafe paths, symlinks/submodules, and budget breaches are contract failures,
not silent exclusions. Metrics expose `seen`, `included`, each exclusion
category, `excluded_bytes`, `included_raw_bytes`, `included_normalized_bytes`,
and `included_chunk_count`; all counters cross-check exactly against the
snapshot.

## 6. Source normalization and canonical documents

For an included blob, decode strict UTF-8 and reject C0/C1 controls other than
TAB, LF, and CR before applying the existing
`TextNormalizationRules.normalize_text` exactly: NFC, CRLF/CR to LF, trailing
whitespace removal per line, three-or-more newline collapse, and boundary LF
removal. Do not normalize raw bytes before source selection or raw-byte
accounting. The normalized text is the only input to `content_hash` and is
encoded as UTF-8 for SHA-256. The empty normalized string is valid.

Build one document with `CanonicalDocumentRecordBuilder` using this exact
projection, then strictly revalidate the builder output before and after schema
validation:

- `document_id`: `git:spen-sdk:{path}`;
- `source_system`: `git`; `source_type`: `code_file`;
- `repo`: `spen-sdk`; `branch`: `develop`; `file_path`: normalized path;
- `source_version`: requested commit; `crawled_at`: supplied input;
- `acl_id`: `acl:repo:spen-sdk`;
- `title`, `space_key`, `page_id`, `url`, `author`, `created_at`, and
  `updated_at`: `None`;
- `jira_keys` and `relation_ids`: empty lists;
- `metadata`: exactly
  `{ "language": <fixed language tag>, "raw_byte_size": <int>,
  "normalized_byte_size": <int>, "symbol_authority": <bool> }`.

The validator enforces exact key sets, enum/format values, content-hash
recomputation, identity fields, JSON-safe metadata, and no aliases. The
application calls `FoundationSchemaValidator.validate_record("CanonicalDocument", ...)`
and maps every schema/builder failure to `schema_validation_failed`.

## 7. Authority map and fallback chunk contract

M9-C owns symbol authority only for C++ and Java. The exact case-insensitive
authority suffix set is `.cc`, `.cpp`, `.cxx`, `.hh`, `.hpp`, `.hxx`, `.inl`,
and `.java`. `.c`, ambiguous `.h`, Kotlin, XML, extensionless files, and all
other accepted text files are M9-B fallback `code_window` inputs. This makes
the authority boundary explicit; no file is silently dropped. M9-B emits no
`code_symbol` records, including for authority files; it returns their
documents and normalized bytes for M9-C.

Use the active validated `ChunkingProfile` (`BAAI/bge-m3`, `medium`,
`chunker_version=1.2.0`) and the injected `TokenizerPort`. For every assembled
chunk text, add the deterministic prefix, then run
`TextNormalizationRules.normalize_text` before tokenization, content hashing,
ID generation, and record construction. Tokenization must be an exact
`TokenizationResult`; every span must be a concrete `CharacterSpan`, have
`0 <= start < end <= len(normalized_text)`, and be strictly non-overlapping
and ordered (`next.start >= previous.end`). A non-empty assembled text must
have at least one span. Any wrong return type, forged offset,
overlap/ordering violation, or unexpected tokenizer exception fails closed.
`token_count` is the validated span count, never a caller-provided value.

Fallback windows use complete source lines, target 450 tokens, hard maximum
1000 tokens, maximum 40 lines, and at most four complete-line overlap lines.
The first short preamble (leading lines before the first blank boundary and
below `minimum_tokens`) is merged into the first following window; if no
following line exists it remains one short valid window. A line that cannot
fit with its prefix under the hard maximum fails as
`unsplittable_code_line`; it is never split or truncated. Overlap is reduced
as needed to fit the hard maximum and never causes an infinite cursor loop.
All windows contain at least one new source line. `line_start` and `line_end`
are one-based inclusive source line numbers; overlapping lines retain their
original numbers. Windows are ordered by source position and use
`unit_key={path}#w{zero_based_window_index}`. `part_index` is zero-based and
`part_total` is the final window count (including a single-window `0/1` pair,
as required by the fallback contract).

The prefix comment-token map is fixed and case-insensitive. XML suffixes are
`.xml`, `.xsd`, `.xsl`, `.xslt`, and `.svg`; SQL is `.sql`; C++/Java/Kotlin/
JavaScript/TypeScript/Go/Rust/C#/PHP use `//` for the exact suffix set
`.cc`, `.cpp`, `.cxx`, `.h`, `.hh`, `.hpp`, `.hxx`, `.inl`, `.java`, `.kt`,
`.kts`, `.js`, `.jsx`, `.ts`, `.tsx`, `.go`, `.rs`, `.cs`, and `.php`;
Python/shell/YAML/TOML/INI/Make/Gradle use `#` for `.py`, `.pyw`, `.sh`,
`.bash`, `.zsh`, `.fish`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.conf`,
`.mk`, `.make`, `.gradle`, plus basenames `Makefile` and `Dockerfile`.
Extensionless and unknown files also use `#`. XML renders
`<!-- spen-sdk \u00b7 {escaped_path} -->`, SQL renders
`-- spen-sdk \u00b7 {escaped_path}`, `//` files render
`// spen-sdk \u00b7 {escaped_path}`, and `#` files render
`# spen-sdk \u00b7 {escaped_path}`. The exact suffix-to-language table is one
immutable map and is tested, so unsupported extensions are never silently
omitted. Prefix path escaping is deterministic UTF-8 percent encoding with
only ASCII alphanumerics, `.`, `_`, `~`, and `/` left unescaped; it prevents
XML `--`/comment termination and newline/control injection without changing
`file_path` or the stable key.

Each record uses `ChunkRecordBuilder` with `source_system=git`,
`source_type=code_file`, `content_kind=code_window`, `language` from a fixed
case-insensitive suffix map or `unknown`, `repo`, `branch`, `file_path`,
`source_version=commit_sha`, `acl_tags=["repo:spen-sdk"]`, `symbol=None`,
`jira_keys=[]`, `relation_ids=[]`, and the active chunker version. Validate
every record against `ChunkRecord`, then enforce line/part pairing, inclusive
range ordering, token-count equality, hard maximum, unique IDs, and duplicate
ID rules from `CHUNKING_SPEC.md` section 3. A byte-identical full preimage may
receive deterministic `-1`, `-2` suffixes; a same-base ID with a different
full preimage is `chunk_id_collision` and fails closed.

## 8. Atomic application API

`BuildGitCodeDocuments` exposes `execute(request)` where the request contains
the validated `GitSourceConfig` and the active `ChunkingProfile`. Its injected
dependencies are the Git read port, tokenizer, schema validator, and pure
builders/ID generator. Before the first dependency call it validates concrete
request/dependency shapes and active profile identity.

Return a frozen `GitCodeBuildResult` with this exact status matrix:

- `status="success"`: `plan` is an exact `CodeDocumentPlan`,
  `error_category is None`, and all metrics equal plan contents.
- `status="failed"`: `plan is None`, `error_category` is one stable enum,
  and no record/byte/path/text field is present.

`CodeDocumentPlan` owns immutable sorted documents, authority-file normalized
bytes, fallback chunks, and metrics. It rejects duplicate document IDs/chunk
IDs, cross-document chunks, unsupported content kinds, bad hashes, impossible
line/part counters, non-contiguous parts, mismatched source identity, and
counter mismatches. The use case first obtains and validates one complete
snapshot, processes into private local collections, validates every record,
then publishes one defensive plan. Any later failure discards all locals and
returns the failed result; no partial output is observable.

## 9. Required tests and validation

Add adversarial tests for every public boundary: `object()`, `None`, wrong
runtime types, forbidden extra fields, forged snapshots/results, malformed
tokenizer spans/results, impossible counters, and impossible status/field
combinations. Add infrastructure tests for:

- exact branch/commit binding, dirty-worktree immunity, wrong SHA, detached
  HEAD, root reparse/symlink, and no network/config/remote mutation;
- fixed argv/environment, timeout/output caps, malformed `ls-tree -z`, invalid
  UTF-8, newline/tab/NFC/casefold/reserved/control paths, symlink/submodule;
- every exclusion and every budget boundary, empty files, invalid UTF-8,
  oversized lines, aggregate failure after an earlier valid file, and atomic
  no-partial-result behavior;
- deterministic repeated scans, canonical document schema negatives, exact
  raw-vs-normalized hashes, prefix escaping, C++/Java authority versus
  Kotlin/XML/extensionless fallback, preamble/overlap/line ranges, tokenizer
  forgery, hard limits, duplicate IDs, and collision handling;
- forbidden side effects: no network, clone/fetch, writes, checkpoint,
  export, raw store, embedding, Qdrant, symbol parser, or sensitive-output
  leakage.

Run, with explicit workspace basetemps where required:

1. focused M9-B model, reader, use-case, and architecture suites;
2. M9-A1/A2/A3 regression suite;
3. M8-D/E page-set/chunker/handoff regression suite;
4. `python -m compileall -q src tests`;
5. scoped `git diff --check` and the repository diff-policy check.

Record exact commands and results in
`.codex-workflow/20260804-m9b/03-implementation.md`. A fresh independent
review session must inspect the production diff and tests, report only P0-P3
findings, and reach `VERDICT: PASS`; re-review is required after every fix.

## 10. Ledger and git gate

Do not modify `.local_ai/ROADMAP.md` or
`.local_ai/IMPLEMENTATION_STATE.md` until independent review is `PASS` and all
scoped validations are green (environment-only skips may be recorded). Then
record M9-B as complete with evidence paths, commit the bounded diff, and push
`codex/m8-m9`. M8-AC remains `pending_external_input` unless the operator
supplies and executes the approved real 10-20 page gate separately.
