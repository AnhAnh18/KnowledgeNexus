RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M9-B Plan Review

## Required revisions

1. **Commit binding:** matching `HEAD` is insufficient if the worktree is
   dirty and files are opened from disk. The reader must either prove a clean
   worktree or read each blob from the pinned commit (`git cat-file`/`git show`)
   with bounded NUL-safe parsing. Add a dirty-file regression.
2. **Read-only Git execution:** pin argv/env, disable prompts/config aliases
   and optional locks, bound process time/output, parse `ls-tree -z` safely,
   and never expose stderr/command output. Test that no network or remote
   mutation can occur.
3. **Path semantics:** define UTF-8/NFC/POSIX normalization, controls/NUL,
   reserved names, NFC+casefold collisions, and whether unsafe entries abort or
   count as exclusions. Metrics must account for invalid UTF-8, oversized,
   unreadable, symlink, and submodule outcomes.
4. **Budgets and identity:** specify finite per-file/run/file-count/tree/output
   limits, relation checks, allowed case-policy values, and clone-root identity.
5. **Ownership:** distinguish raw bytes from normalized text/bytes, define
   exact hash input, empty-file behavior, defensive copies, and aggregate memory
   limits.
6. **Document projection:** enumerate every CanonicalDocument field/default and
   metadata allowlist. Revalidate builder output strictly; do not rely on the
   permissive existing builder alone.
7. **Chunking alignment:** require the validated BGE-M3 profile/tokenizer,
   exact CHUNKING_SPEC normalization, preamble/empty-file/overlap behavior,
   hard limits, and line-range convention.
8. **Authority map:** use exactly C++/Java as M9-C symbol-authority suffixes;
   define case handling and policy for extensionless/XML/Kotlin/partial files.
9. **Atomic API:** name application request/result/error types, preflight all
   dependencies before the first read, sanitize failures, and return no partial
   result after a later-file failure.
10. **Acceptance:** add dirty-worktree, malformed path, symlink/submodule,
    collision, all budget boundaries, oversized line, tokenizer forgery, bad
    counters, deterministic repeat, schema-negative, and forbidden-side-effect
    tests.

The revised plan must be implementation-ready before any production edit.
