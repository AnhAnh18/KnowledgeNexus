# M5A Confluence Inventory Core Review Summary

## Outcome

M5A is complete. It adds a deployment-independent Confluence inventory core,
deterministic scope policy, application orchestration, and two deterministic
internal report files. M3/M4 production behavior and Foundation JSON Schemas
are unchanged.

The concrete Confluence deployment, REST endpoint/version, pagination payload,
and sanitized API fixtures remain unresolved. Those decisions intentionally
block M5B adapter selection, not the M5A core.

The independent-review P1/P2 findings were accepted and fixed:

- P1: report publication now uses atomic same-directory hard-link creation,
  which cannot overwrite a concurrently created destination.
- P2: CSV scalar strings beginning with `=`, `+`, `-`, or `@` are prefixed
  with an apostrophe; JSONL retains the original source value.
- P2: metadata and config collection fields reject scalar `str`/`bytes` before
  materialization, preventing character-tuple corruption.
- P2: ordered ancestor ID/title fields reject set/dict and require a
  non-string `Sequence`; labels retain unordered-input support because they are
  normalized by sort/deduplication.

## Files Changed

Production/package files:

- `src/knowledgenexus/foundation/domain/models/__init__.py`
- `src/knowledgenexus/foundation/domain/models/confluence_source_config.py`
- `src/knowledgenexus/foundation/domain/models/confluence_page_metadata.py`
- `src/knowledgenexus/foundation/domain/models/confluence_inventory_item.py`
- `src/knowledgenexus/foundation/domain/rules/confluence_scope_policy.py`
- `src/knowledgenexus/foundation/ports/__init__.py`
- `src/knowledgenexus/foundation/ports/confluence_inventory_port.py`
- `src/knowledgenexus/foundation/application/__init__.py`
- `src/knowledgenexus/foundation/application/use_cases/__init__.py`
- `src/knowledgenexus/foundation/application/use_cases/build_confluence_inventory.py`
- `src/knowledgenexus/foundation/infrastructure/exporters/confluence_inventory_report_writer.py`

Tests:

- `tests/foundation/domain/models/test_confluence_source_config.py`
- `tests/foundation/domain/rules/test_confluence_scope_policy.py`
- `tests/foundation/application/use_cases/test_build_confluence_inventory.py`
- `tests/foundation/infrastructure/exporters/test_confluence_inventory_report_writer.py`
- `tests/foundation/integration/test_confluence_inventory_core.py`

Local-only state/review files:

- `.local_ai/IMPLEMENTATION_STATE.md`
- `.local_ai/ROADMAP.md`
- `.local_ai/review/m5a-confluence-inventory-core-review-summary.md`
- `.local_ai/review/m5a-confluence-inventory-core.patch`

## Architecture and Layer Ownership

- `foundation.domain.models` owns immutable non-secret config, normalized page
  metadata, and internal inventory items. These models perform no filesystem,
  network, environment, or JSON Schema work.
- `foundation.domain.rules.ConfluenceScopePolicy` is pure and deterministic.
- `foundation.ports.ConfluenceInventoryPort` describes only normalized metadata
  needed by the application. It hides raw API JSON, HTTP/authentication,
  endpoints, and pagination transport details.
- `foundation.application.use_cases.BuildConfluenceInventory` orchestrates
  roots, validates the port contract, deduplicates, applies policy, and sorts.
- `foundation.infrastructure.exporters.ConfluenceInventoryReportWriter`
  serializes already-classified items. It does not classify scope or connect to
  Confluence.

## Public APIs

```python
ConfluenceIncludeRoot(page_id: str, name: str | None = None)
ConfluenceExcludeSubtree(page_id: str, reason: str | None = None)

ConfluenceSourceConfig(
    source_id: str,
    space_key: str,
    include_roots: tuple[ConfluenceIncludeRoot, ...],
    exclude_subtrees: tuple[ConfluenceExcludeSubtree, ...] = (),
    include_keywords: tuple[str, ...] = (),
    exclude_keywords: tuple[str, ...] = (),
    page_size: int = 50,
)

ConfluenceInventoryPort.iter_page_metadata(
    *, space_key: str, root_page_id: str, page_size: int
) -> Iterable[ConfluencePageMetadata]

BuildConfluenceInventory(*, inventory_port: ConfluenceInventoryPort)
BuildConfluenceInventory.execute(
    *, config: ConfluenceSourceConfig
) -> tuple[ConfluenceInventoryItem, ...]

ConfluenceScopePolicy.decide(
    *, page, include_root_ids, exclude_subtrees
) -> tuple[scope_status, scope_reason]

ConfluenceInventoryReportWriter.write(
    *, output_dir: Path, items: Sequence[ConfluenceInventoryItem]
) -> int
```

## Config and Model Shapes

`ConfluenceSourceConfig` contains only source/scope values: `source_id`,
`space_key`, include roots, excluded subtrees, keyword hints, and preferred page
size. It contains no base URL, PAT/token, username, API version, endpoint,
cursor, retry, rate-limit, or checkpoint value. Root/exclusion IDs are unique,
must not overlap, and at least one include root is required. Page size is a
positive actual integer; bool is rejected. Collections are copied to tuples.

`ConfluencePageMetadata` fields are `page_id`, `title`, `space_key`, optional
`parent_page_id`, ordered `ancestor_page_ids`, ordered `ancestor_titles`,
optional `updated_at`, optional `source_version`, deterministic unique sorted
`labels`, and optional `attachment_count`. Unknown attachment count is `None`;
known zero is `0`; negative, bool, and non-integer counts fail. Ancestor
ID/title inputs must be ordered non-string `Sequence` instances, so list/tuple
order is preserved while set/dict inputs fail. Labels reject scalar strings and
bytes but accept unordered collections because output is unique and sorted.
Config include-root, exclusion, and keyword collections reject scalar strings
and bytes.

`ConfluenceInventoryItem` flattens the normalized metadata and adds `source_id`,
`scope_status`, and `scope_reason`. The only statuses are `included` and
`excluded_subtree`. It has no stored `page_path`, `crawl_eligible`, or runtime
crawl state.

## Port and Root Contract

The port must return the requested root itself and all normalized descendants
for that traversal. `BuildConfluenceInventory` consumes each returned iterable
once and fails when:

- the requested root is absent from its own traversal;
- any page has a different `space_key`;
- a non-root page does not contain the requested root in ordered ancestor IDs;
- the port returns a value that is not `ConfluencePageMetadata`.

No HTTP or pagination envelope leaks through the port.

## Scope Policy

Exclusion overrides inclusion. Exact page exclusion wins and produces
`excluded_page:<page_id>`. Otherwise the nearest matching excluded ancestor is
selected by scanning structural ancestor order from parent toward root and
produces `excluded_ancestor:<page_id>`. Non-excluded include roots produce
`included_root`; other returned pages produce `included_descendant`.

Excluded items remain in the inventory. Include/exclude keyword hints are not
inputs to the policy and cannot remove pages or change hard scope status.
Configured human exclusion reasons remain in config and are not appended to
the stable machine reason.

## Deduplication and Deterministic Ordering

Include roots are traversed by page ID, independent of configuration order.
Overlapping root traversals deduplicate on `page_id`. Identical frozen normalized
metadata is accepted once. Any metadata conflict for one `page_id` raises
`ValueError`; API order is never used as a tiebreaker.

Final items are sorted by:

```text
(space_key, tuple(ancestor_page_ids), page_id)
```

Titles, locale rules, API response order, root configuration order, and set/dict
iteration order do not control output.

## Report Formats and Failure Behavior

The writer requires an existing directory and writes exactly:

- `pages_inventory.jsonl`: UTF-8/no BOM, strict compact sorted-key JSON,
  `ensure_ascii=False`, no non-finite values or `default=str`, one trailing LF
  for non-empty output, zero bytes for empty input. Tuples serialize as arrays;
  `None` remains JSON null. `page_path` is derived from ancestor titles plus
  title only while serializing.
- `inventory_report.csv`: UTF-8/no BOM, fixed 14-column order, LF line endings,
  and one header even for empty input. Tuple cells are compact JSON arrays.
  Optional scalars use empty cells; attachment count zero uses `0`. Scalar
  strings with a spreadsheet-formula prefix (`=`, `+`, `-`, `@`) receive a
  leading apostrophe in CSV only.

Targets are atomically created without clobbering by hard-linking closed
same-directory temporary files. Unlike `Path.replace()`, `os.link()` raises
`FileExistsError` if a concurrent writer creates the destination at any point
before publication. The temp hard link is retained until both targets publish,
so rollback removes a target only when `samefile()` confirms it is still the
writer-owned file. Temporary-write or publish failures propagate the original
exception. Cleanup does not remove the output directory, concurrent/caller
files, or unrelated entries and does not mask the original error.

## Roadmap Change

The old single M5 milestone is now:

- M5A core/scope/reports: complete, no HTTP.
- M5B adapter: next, only after deployment/API confirmation and sanitized
  fixtures; owns raw mapping, root fetch, descendants query, and basic
  correctness pagination.
- M5C small real inventory smoke run: follows M5B and precedes content crawl.
- M6 remains the first real page content vertical slice.
- M7 owns pagination hardening, retry, rate limiting, `Retry-After`, checkpoint,
  resume, and partial-failure isolation.

## Intentionally Deferred

- M5B: Cloud/Data Center choice, endpoint/version, authentication injection,
  HTTP client, raw payload mapping, root fetch, descendant query, and basic
  correctness pagination.
- M5C: any real-source smoke run and manual subtree selection.
- M6: raw page/body/ACL fetch, normalization, chunking, relations, and real-page
  snapshot production.
- M7: rate limits, retries, `Retry-After`, pagination hardening, checkpointing,
  resumability, and failure isolation.
- All attachment download/processing, SyncState/tombstone behavior, Indexing,
  Retrieval, Chat, Qdrant, and Gauss work.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/models/test_confluence_source_config.py -q
40 passed in 0.29s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/models/test_confluence_source_config.py tests/foundation/domain/rules/test_confluence_scope_policy.py tests/foundation/application/use_cases/test_build_confluence_inventory.py tests/foundation/infrastructure/exporters/test_confluence_inventory_report_writer.py tests/foundation/integration/test_confluence_inventory_core.py -q
66 passed in 1.45s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain tests/foundation/application/use_cases tests/foundation/infrastructure/exporters tests/foundation/integration -q
447 passed in 8.85s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared -q
473 passed in 9.24s

git diff --check
PASS (exit 0; existing LF-to-CRLF working-copy warnings only)

git diff --cached --check
FAIL (exit 2) only for pre-existing trailing whitespace on line 1 of
`AI_Knowledge_Platform_Master_Spec_v7.md` and
`AI_Knowledge_Platform_Master_Spec_v7_1.md`; both are outside all M5A patches.

git apply --reverse --check .local_ai/review/m5a-confluence-inventory-core.patch
PASS (exit 0)

git apply --reverse --check .local_ai/review/m5a-1-domain-scope.patch
PASS (exit 0)

git apply --reverse --check .local_ai/review/m5a-2-inventory-use-case.patch
PASS (exit 0)

git apply --reverse --check .local_ai/review/m5a-3-inventory-reporting.patch
PASS (exit 0)
```

No formatter, linter, or type checker is configured in the repository, so no
new tooling was introduced or run.

## Differences from Prompt

There is no behavioral or boundary departure. The preferred model files were
kept separate. Closely related metadata-model tests are consolidated in the
source-config model test module. The writer also rolls back its first owned
published report if publication of the second report fails, strengthening the
requested no-partial-artifact failure policy without introducing a generic
transaction abstraction.
CSV formula neutralization and explicit scalar-collection rejection are
accepted security/correctness review fixes beyond the original happy-path
examples; they do not expand the M5A architecture boundary.
Requiring ordered sequences for ancestor structural paths is an accepted
determinism review fix and does not change valid list/tuple callers.

## Patch Discipline

`m5a-confluence-inventory-core.patch` is the replacement full/squashed M5A
patch and supersedes the previous full M5A patch. Apply it after the approved
`m4-golden-full-snapshot-export.patch`. It contains only the 11
production/package files and 5 tests listed above. It excludes `.local_ai`,
dependency files, generated reports, and unrelated existing working-tree
changes.

For smaller submissions, use this incremental series instead of the full patch:

1. `m5a-1-domain-scope.patch` — 7 files, 25,869 bytes; apply after M4.
2. `m5a-2-inventory-use-case.patch` — 6 files, 13,855 bytes; apply after patch 1.
3. `m5a-3-inventory-reporting.patch` — 3 files, 21,719 bytes; apply after patch 2.

Do not apply both the full patch and the split series. All four patch artifacts
exclude `.local_ai`, dependency files, generated reports, and unrelated
working-tree changes.
