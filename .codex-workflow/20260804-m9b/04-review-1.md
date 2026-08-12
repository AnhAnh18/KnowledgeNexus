P1 — Aggregate memory budget is never enforced. `max_in_memory_bytes` is validated only as a configuration upper bound; neither the reader nor application accounts for raw bytes, normalized text, records, or chunks before publishing success. A scan can exceed the configured owned-memory budget while returning `success` (`local_git_repository_reader.py:216-301`, `build_git_code_documents.py:127-159`, `git_code_source.py:145-170`).

P1 — Tokenizer span validation accepts negative and zero-length spans. `_validated_token_count` checks overlap and upper bounds but never enforces `0 <= start < end`, allowing forged `TokenizationResult` values to determine token counts and pass chunk construction (`build_git_code_documents.py:395-413`).

P1 — Forged repository snapshots are not semantically revalidated. `GitRepositorySnapshot` validates only basic types, ordering, and aggregate counters; it does not verify raw/normalized consistency or that `symbol_authority` matches the path. The application trusts these fields, so a forged snapshot can suppress fallback chunks or emit documents from mismatched content (`git_code_source.py:272-297`, `build_git_code_documents.py:117-136`).

P1 — Chunk cross-field invariants are incomplete. `CodeDocumentPlan` and `_validate_plan` do not enforce exact record fields, file-path/document agreement, content-kind/language/ACL identity, contiguous parts, consistent `part_total`, valid line ranges, or chunk token/hash invariants. A forged chunk builder can therefore produce a schema-valid but semantically inconsistent successful plan (`git_code_source.py:319-355`, `build_git_code_documents.py:383-440`).

P1 — The exported subprocess runner accepts arbitrary Git argv, including remote or mutating commands and user-controlled options. Only `shell=False` and environment flags are enforced; there is no argv allowlist, so direct use of `SubprocessGitCommandRunner` can violate the read-only/no-network contract (`local_git_repository_reader.py:151-190`).

P1 — Output caps are not enforced at the injected-runner boundary, and the subprocess implementation captures unbounded stdout/stderr before checking caps. A malformed runner or Git process can allocate output far beyond the declared limits (`local_git_repository_reader.py:181-200`, `local_git_repository_reader.py:319-337`).

P2 — `GitSourceConfig` does not enforce its stated root invariant. The constructor accepts nonexistent paths, non-directories, symlink/reparse roots, and paths whose ancestors are reparse points; these are rejected only later by the adapter (`git_code_source.py:183-196`, `local_git_repository_reader.py:303-317`).

P2 — Tree parsing is less strict than the contract. Object IDs are checked only for length, not lowercase hexadecimal, and C1 control characters are accepted in tree paths (`local_git_repository_reader.py:350-372`, `local_git_repository_reader.py:428-446`; `git_code_source.py:101-123`).

P2 — `BuildGitCodeDocuments.__init__` accepts `None`, `object()`, and malformed dependencies without rejection, despite the required constructor-boundary validation; validation is deferred until `execute` (`build_git_code_documents.py:96-112`, `build_git_code_documents.py:171-185`).

VERDICT: FAIL