# M7-C2-A SQLite Checkpoint Schema Review Summary

## Scope

M7-C2-A adds the durable v1 SQLite schema, exact catalog verification,
validated workspace/path admission, read-only unknown-state preflight,
durability PRAGMA setup, and the sanitized checkpoint-state port/error
surface. It deliberately does not implement the writer lock, lease, database
opener, run registry, checkpoint mutations, orchestration, retry, CLI, network,
migration, repair, backup, or retention behavior.

## Decisions Recorded

- C2-A owns no lease, lock capability, workspace object, or database opener.
  C3-A owns portalocker acquisition, the live OS handle, lease construction,
  SQLite open/close ordering, and child-process contention acceptance.
- C2-A exposes only private guard, read-only preflight/catalog, and connection
  initializer seams. The initializer requires an exact explicit `bool`:
  `True` only after C3-A observed an absent database; `False` validates the
  complete catalog before writable PRAGMAs; `None` and non-bools fail closed.
- Workspace admission accepts only the concrete platform `pathlib.Path`,
  rejects lexical traversal/relative/UNC/file paths, and uses `lstat` for all
  ancestors, database/lock entries, SQLite sidecars, symlinks, and reparse
  points. Dangling entries are not treated as missing unless `lstat` raises
  `FileNotFoundError`.
- Schema identity is the tuple `application_id=1263425591`,
  `user_version=1`, and the singleton metadata row
  `knowledgenexus.m7.checkpoint.v1`. Unknown state is read-only and fail
  closed; no migration or repair is attempted.
- Catalog comparison normalizes whitespace only and preserves case/literals.
  Exact table info, foreign-key rows, explicit and automatic index lists,
  index-xinfo rows, metadata, foreign-key check, and integrity check are
  verified.
- Durability is `foreign_keys=ON`, `busy_timeout=0`, `journal_mode=DELETE`,
  and `synchronous=EXTRA`, with readback required. Initializer failures
  rollback, close, and return body-free `checkpoint_failure` errors.
- The public port exposes only `CheckpointSchemaState`,
  `ConfluenceCheckpointStatePort`, `CheckpointFailureCategory`, and
  `CheckpointStateError`; invalid DTO values map to the same sanitized error.

The boundary correction is recorded at
`.codex-workflow/20260801-160919-051bd6a7/03-plan-revised-c2a-boundary.md`.

## Independent Review

Fresh independent technical and governance sessions reviewed the final
snapshot, the boundary revision, source/tests, exact catalog, path/reparse
behavior, no-write evidence, PRAGMA readback, and scope exclusions.

```text
Technical: VERDICT: PASS
Governance: VERDICT: PASS
```

## Validation

```text
python -m pytest -q tests/foundation/ports/test_confluence_checkpoint_state_port.py tests/foundation/infrastructure/checkpoint --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c2a-final16-focused
59 passed, 12 skipped

python -m pytest -q tests/foundation/domain/models/test_confluence_crawl_run.py tests/foundation/domain/models/test_confluence_inventory_occurrence.py tests/foundation/domain/rules/test_confluence_inventory_occurrence_resolver.py --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c2a-final16-c1b
28 passed

python -m pytest -q tests/foundation/application/use_cases/test_build_confluence_inventory.py tests/foundation/infrastructure/confluence --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c2a-final16-compat
316 passed

python -m pytest -q tests/architecture/test_application_import_boundary.py --basetemp D:\Claude\KnowledgeNexus\.pytest-codex-m7-c2a-final16-architecture
11 passed

python -m compileall -q src/knowledgenexus/foundation/ports/confluence_checkpoint_state_port.py src/knowledgenexus/foundation/infrastructure/checkpoint
PASS

git diff --check
PASS (existing LF/CRLF warning only)
```

The skipped probes are capability-gated symlink cases; the Windows junction
probe ran and rejected a real junction.

## Closure Boundary

M7-C2-A is implemented, validated, and independently reviewed. C3-A is the
next stage for the actual OS writer lock, lease ownership, locked SQLite open,
and close-before-unlock integration.
