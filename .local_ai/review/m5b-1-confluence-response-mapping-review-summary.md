# M5B-1 Confluence Data Center Response Mapping Review Summary

## Scope

M5B-1 adds only pure, offline response parsing and metadata normalization:

- `ConfluenceDataCenterPageMetadataMapper`
- immutable `ParsedConfluenceSearchPage`
- three minimal sanitized Data Center-shape fixtures
- focused mapper, envelope, fail-closed, and fixture-safety tests

No HTTP client, authentication, environment access, CQL construction,
pagination loop, retry, body/attachment retrieval, or production port adapter is
part of this patch.

## Contract decisions

- Root mapping remains compatible with the captured root payload. Missing
  `space` falls back to the caller's expected space; an observed `space.key` is
  validated and must match.
- Missing root `metadata.labels` normalizes to `()`; present labels are parsed
  and deterministically normalized by `ConfluencePageMetadata`.
- Descendants require the confirmed search-response space and labels shape.
  The labels envelope must be a complete first window: numeric
  `start`/`limit`/`size` must be consistent and `_links.next` must not identify
  another label window.
- Raw ancestors above the selected root are removed. The selected root must
  occur exactly once, the root-relative ID/title path remains aligned, and the
  final retained ancestor becomes `parent_page_id`.
- Numeric envelope validation rejects bools, inconsistent windows, and
  non-advancing non-terminal pages. Terminal state is derived only from
  `start + size >= totalSize`, never from `/_links.next`.
- M5B-2 must request root `expand=space,version` and enforce presence/match of
  root `space.key` inside the concrete adapter before yielding metadata. M5B-1
  exposes no strict-mode flag for that future adapter postcondition. This
  additive expansion was not observed by M5B-0; it is a deliberate
  scope-correctness requirement to confirm during M5C.
- The packet sanitizer replaces `totalSize` and `searchDuration` with negative
  sentinels, so the sanitized packet cannot replay numeric envelope values. The
  committed fixtures use synthetic consistent totals derived from the recorded
  four-window sequence and terminal decision in the request trace.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/infrastructure/confluence/test_confluence_data_center_page_metadata_mapper.py -q
44 passed in 1.42s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation/domain/models/test_confluence_source_config.py tests/foundation/domain/rules/test_confluence_scope_policy.py tests/foundation/application/use_cases/test_build_confluence_inventory.py tests/foundation/infrastructure/exporters/test_confluence_inventory_report_writer.py tests/foundation/integration/test_confluence_inventory_core.py tests/foundation/infrastructure/confluence/test_confluence_data_center_page_metadata_mapper.py -q
110 passed in 3.60s

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation tests/shared --ignore=tests/foundation/infrastructure/confluence/test_confluence_data_center_inventory_adapter.py -q
517 passed in 18.72s

git diff --cached --check
PASS

clean clone of HEAD + git apply m5b-1-confluence-response-mapping.patch
focused M5B-1 tests: 44 passed in 0.97s
full Foundation/Shared: 517 passed in 22.56s
git diff --check: PASS
git apply --reverse --check: PASS
real deployment identifier scan: PASS

```

Fixture scanning uses an allowlist of exact synthetic keys/scalars and generic
checks for credential/header/URL/email markers. No real hostname, space key,
page ID, or PAT prefix is embedded in the committed test source.

## Local review result

Independent review found one P2: the original fixture denylist embedded real
deployment identifiers in committed test source. It is resolved by the
synthetic allowlist and a regression proving unknown sanitized scalars fail.
The two actionable P3 hardening items were also resolved: duplicate retained
ancestors fail closed, and labels envelope inconsistency/pagination fails
closed. The evidence-sentinel and unobserved-root-expansion P3 notes are now
recorded explicitly; neither required changing the numeric parser or M5B-1 root
fallback behavior.

M5B-2 work appeared concurrently during final verification:
`confluence_data_center_inventory_adapter.py`,
`confluence_http_transport.py`,
`test_confluence_data_center_inventory_adapter.py`, and extra M5B-2 exports in
`confluence/__init__.py`. The M5B-1 index/patch contains only the mapper exports
in `__init__.py`; the richer M5B-2 working-tree version and the other three files
were preserved but excluded because they contain HTTP/adapter behavior outside
this task.

## Optional split submission series

Apply in this exact order:

1. `m5b-1-1-data-center-mapper.patch` - package export and pure production
   mapper/envelope implementation (2 files, 464 inserted lines).
2. `m5b-1-2-sanitized-fixtures.patch` - three synthetic response fixtures
   (3 files, 141 inserted lines).
3. `m5b-1-3-mapper-tests.patch` - focused mapping, fail-closed, pagination, and
   fixture-safety tests (1 file, 602 inserted lines).

The series was applied in order to a clean clone. Patch 1 passed compile-check,
patch 2 parsed as JSON, and the complete series passed all 44 focused tests plus
`git diff --check`. Reverse checks passed for all three patches. The split
series is content-equivalent to the combined M5B-1 patch and excludes all
`.local_ai` and concurrent M5B-2 files.
