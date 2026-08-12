# M9-B Independent Re-review (fix implementation)

Scope: revised plan, fix artifact, and M9-B production/tests only. No source files were edited.

## Findings

### P1 — `CodeDocumentPlan` accepts semantically forged records

`CodeDocumentPlan.__post_init__` checks only record key sets, ID syntax, and chunk hashes/IDs. It does not validate document content hashes or exact source/schema/ACL/version fields, does not require `content_kind == "code_window"`, and does not enforce chunk `file_path` to the document's path or chunk source identity/profile. The plan contract explicitly requires these cross-field checks at the model boundary, so a caller can construct and publish a successful `GitCodeBuildResult` containing a schema-shaped but forged plan. Reproduction accepted a document with `source_system="evil"`, `repo="evil"`, `content_hash="0"*64`, and `schema_version="bad"` at `git_code_source.py:338-486`.

### P1 — Forged non-integral tokenizer offsets are accepted

`BuildGitCodeDocuments._validated_token_count` checks span ordering and bounds but never checks that `start` and `end` are exact integers. A tokenizer can forge a `CharacterSpan` via `object.__new__` with offsets `0.5` and `1.5`; `TokenizationResult` accepts it and the use case returns `success` with a token count derived from the forged span. This violates the required exact `0 <= start < end <= len(text)` concrete-span contract at `build_git_code_documents.py:472-495`.

### P2 — `LocalGitRepositoryReader` constructor accepts an invalid runner

The public constructor stores any non-`None` `runner` without validating its runtime shape. `LocalGitRepositoryReader(runner=object())` constructs successfully, despite the requirement that public constructors reject `object()`/malformed dependencies before use. Validation is deferred until `read`, where the failure is mapped to a repository-read error, at `local_git_repository_reader.py:251-255`.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review2` -> `25 passed`.
- Focused adversarial probes confirmed: forged plan -> accepted; forged float tokenizer span -> `success`; invalid reader runner -> accepted by constructor.

VERDICT: FAIL
