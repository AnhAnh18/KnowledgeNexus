# M9-B Initial Plan: Local Git Repository and Code-Document Seam

## Goal

Add a read-only, local-clone Git source seam for the canonical `spen-sdk`
repository on branch `develop`. The stage must produce schema-valid
`CanonicalDocument` records for accepted source files and final deterministic
`code_window` `ChunkRecord`s only for languages without M9-C symbol authority.
The seam is offline and bounded: no clone, fetch, remote access, raw-store
write, export, checkpoint mutation, embedding, Qdrant, or symbol parsing.

## Locked source identity

- `repo_name` is exactly `spen-sdk`.
- `branch` is exactly `develop`.
- `commit_sha` is one exact lowercase 40-hex full commit hash supplied by the
  caller and must match the local clone's checked-out `HEAD`.
- `document_id` is `git:spen-sdk:{posix_file_path}`.
- `document_stable_key` and every chunk preimage use `git:spen-sdk:{path}`;
  branch and commit are provenance only.
- Git ACL is `acl_id=acl:repo:spen-sdk` and `acl_tags=["repo:spen-sdk"]`.
- `crawled_at` is an explicit RFC3339 input; no wall clock is read.

## Bounded models and port

1. `GitSourceConfig` is immutable and runtime-validated. It carries an
   absolute local clone root, exact repository/branch/commit identity,
   `crawled_at`, per-file/per-run/per-file-count budgets, and an explicit
   case policy (`reject_casefold_collisions`). It rejects `object()`, `None`,
   wrong enum/type values, relative roots, non-40-hex commits, invalid
   timestamps, impossible budgets, and extra fields.
2. `GitFileObservation` is immutable, repr-safe, and carries one normalized
   POSIX-relative path plus immutable raw UTF-8 bytes and byte count. It
   rejects absolute paths, `..`, backslashes, empty components, control
   characters, duplicate/casefold-colliding paths, and oversized bytes.
3. `GitScanMetrics` is immutable with counters for seen, included, and each
   exclusion category (`generated`, `vendor`, `build`, `binary`) plus bytes;
   counters must be non-negative and cross-check exactly against the snapshot.
4. `GitRepositorySnapshot` is immutable, sorted by path, binds repo/branch/
   commit to the requested config, deep-rebuilds nested observations, and
   rejects duplicate paths, impossible counters, and mismatched identities.
5. `GitRepositoryReadPort` is a protocol with one read operation returning a
   `GitRepositorySnapshot`; port and application errors expose only stable
   category enums and never command output, paths, source text, or exception
   reprs.

## Exact filesystem and exclusion policy

- The local reader verifies the root is an existing directory whose final
  component is exactly `spen-sdk`, the work tree is local, `HEAD` resolves to
  the requested full hash, and the symbolic branch is exactly `develop`.
- It uses only read-only local Git commands (`rev-parse`, `symbolic-ref`,
  `ls-tree`) with argument arrays, no shell, no remote/config mutation, and
  no network-capable command. A failed command maps to a sanitized category.
- Git tree entries with symlink or submodule modes are rejected, not followed.
  Unsafe/ambiguous POSIX paths and casefold collisions fail closed.
- Generated paths are excluded when a component or filename matches the fixed
  set: `generated`, `gen`, `build`, `dist`, `out`, `target`, `node_modules`.
- Vendor paths are excluded for components: `vendor`, `third_party`,
  `external`, `Pods`.
- Binary paths are excluded for fixed extensions: images, archives, compiled
  objects, shared libraries, executables, fonts, and PDFs. A NUL byte in an
  otherwise candidate text file is also classified as binary.
- Included files must be regular, readable, valid UTF-8, within the per-file
  and aggregate byte/file budgets, and are normalized only after read:
  NFC, CRLF/CR to LF, and trailing spaces/tabs removed per line. Line order,
  blank lines, and a final newline are preserved.

## Code-document and fallback chunk output

- Build one `CanonicalDocument` per included file using the existing
  `CanonicalDocumentRecordBuilder`, with `source_system=git`,
  `source_type=code_file`, repo/branch/path/commit provenance, exact hash of
  normalized text, and `acl_id=acl:repo:spen-sdk`.
- Validate every document with `FoundationSchemaValidator` before returning.
- C++/C/headers and Java files are symbol-authority files for M9-C; M9-B
  returns their documents and raw normalized bytes but emits no competing
  final chunks.
- Every other included text file emits deterministic `code_window` chunks.
  Windows contain complete lines, use the active `ChunkingProfile` and
  injected `TokenizerPort`, target `code_window_target_tokens`, never exceed
  `hard_maximum_tokens` or `code_window_max_lines`, and use at most
  `code_window_overlap_lines` complete-line overlap. A single line that
  cannot fit fails closed as `unsplittable_code_line`.
- Prefixes are deterministic and part of normalized/hash/token text:
  `// spen-sdk · path` for source-like files and `<!-- spen-sdk · path -->`
  for XML. `unit_key` is `{path}#w{zero_based_window_index}`. IDs come only
  from `ChunkIdGenerator.generate_chunk_id("git", stable_key, unit_key, text)`.
- Build fallback chunks with `ChunkRecordBuilder`, fields
  `source_system=git`, `source_type=code_file`, `content_kind=code_window`,
  language from a fixed suffix map or `unknown`, repo/branch/file_path,
  line_start/line_end, part_index/part_total, `source_version=commit_sha`,
  `acl_tags=["repo:spen-sdk"]`, and `chunker_version=1.2.0`. Validate every
  chunk with the schema validator; no `code_symbol` chunks are emitted here.
- `CodeDocumentPlan` is immutable, sorted, defensive, and contains config
  identity, ordered documents, normalized file bytes/provenance, fallback
  chunks, and aggregate metrics. It rejects cross-field document/chunk IDs,
  invalid line/part counters, duplicate IDs, non-contiguous parts, invalid
  hashes, and unsupported chunk kinds.

## Acceptance tests

- Model adversarial tests cover `object()`, `None`, forged dataclasses,
  forbidden extra fields, wrong enums/types, invalid paths, unsafe symlinks,
  duplicate/casefold paths, impossible counters, and config/HEAD mismatch.
- Local-reader tests use a synthetic local Git repository and prove exact
  branch/commit binding, no network/remote mutation, deterministic tree order,
  exclusion counters, symlink/submodule rejection, size/file budgets,
  invalid UTF-8/binary handling, and sanitized failures.
- Application tests prove schema-valid CanonicalDocument/ChunkRecord output,
  symbol-authority C++/Java no-chunk behavior, fallback windows, line and
  token budgets, deterministic repeat output, mutation-safe ownership, and
  no raw/credential/path leakage.
- Architecture tests forbid application-to-infrastructure imports and all
  network, clone/fetch, export, checkpoint, embedding, Qdrant, and symbol
  parser imports in the M9-B boundary.
- Run focused M9-B tests, M9-A regressions, M8-D/E handoff regressions,
  architecture tests, compileall, and scoped diff-check. Obtain an
  independent review in a fresh session; only `VERDICT: PASS` permits ledger
  updates and commit/push.
