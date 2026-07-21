# M6B Page-Adjacent Confluence Observations - Implementation Summary

## Status

- `M6B_BASE_COMMIT`: `6b23ed3`
- Implementation stack:
  - `bed4422` `[M6B-A]` status-aware HTTP observation capability and tests;
  - `23e763e` `[M6B-B]` page-observation domain/port/adapter/raw-store
    primitives and tests;
  - `4c9eb7d` `[M6B-C]` bounded restriction/attachment orchestration and tests;
  - `56e1e71` `[M6B-D]` sanitized operator CLI and offline tests;
  - `[M6B-F]` this documentation/state registration.
- Production `REVIEW_HEAD`: `56e1e71`.
- Detached reviewer: Claude, Extra High.
- Detached review: approved after focused round 2.
- Controlled live run: pending.
- The repository owner explicitly authorized this local commit-based review
  stack. The round-1 stack was pushed through `8b4986c` for detached review.
- No live network request was performed on this checkout.
- M6C was not started.

## Detached review round 1

Verdict: **Changes required**. No P0 finding. The original implementer accepted
and implemented these focused changes in the working tree:

- **P1 attachment identity:** attachment IDs no longer pass through the numeric
  page-ID rule. A dedicated rule preserves both REST forms documented across
  Confluence Server/Data Center versions: ASCII decimal (`123`) and legacy
  `att`-prefixed decimal (`att123`). Page IDs remain strictly numeric. The rule
  is intentionally no broader than these two documented forms.
- **P2 HTTPError body read:** an I/O/protocol failure while reading the body of
  an `HTTPError` is now wrapped as body-free `ConfluenceHttpError`; the explicit
  response-size exception still passes through unchanged.
- **P3 raw-page path handoff:** a new integration test writes with the production
  M6A `ConfluenceRawPageStore` and reads the exact bytes with the production M6B
  `ConfluencePageObservationStore`.

Evidence basis for the compatibility rule:

- legacy Server REST attachment-list examples use IDs such as `att5678`:
  <https://docs.atlassian.com/atlassian-confluence/REST/5.7.5/>;
- current Data Center attachment APIs define attachment IDs as strings and use
  decimal examples in attachment operations:
  <https://developer.atlassian.com/server/confluence/rest/v911/api-group-attachments/>.

The non-blocking P3 observations remain unchanged and explicit: an unexpected
HTTP status deliberately replaces the deterministic restriction body with the
latest observed body before failing operationally; CLI `KeyboardInterrupt`
continues to map through the fixed unexpected category; internal assertions are
not security checks.

Focused-fix verification:

```text
python -m pytest <eight focused M6B/fix paths> -q
145 passed in 3.67s

python -m pytest tests/foundation tests/shared tests/architecture -q
809 passed in 21.10s

git diff --check
PASS (line-ending warnings only on this Windows checkout)
```

Focused re-review verification:

```text
python -m pytest <focused M6B/fix paths> -q
191 passed in 4.65s

python -m pytest tests/foundation tests/shared tests/architecture -q
809 passed in 22.74s

git diff --cached --check
PASS
```

Fix status: focused detached re-review approved; `[M6B-E]` commit authorized by
the repository owner. No controlled live request was made.

## Public behavior

For one numeric selected page ID, M6B reads the existing M6A artifact at
`<raw_root>/confluence/pages/<page_id>.json` through a Foundation port. It
validates the raw page and ordered ancestors before making a network call. It
then:

1. fetches view-restriction observations for every ancestor in source order and
   the selected page last;
2. preserves each exact response body before normalization;
3. fetches attachment metadata beginning at `start=0` with the configured limit;
4. preserves each exact window before parsing it;
5. follows only the server-observed, validated `_links.next`; and
6. returns restriction and attachment observations as plain JSON-compatible
   dictionaries.

The CLI is:

```text
python -m knowledgenexus.foundation.cli.collect_confluence_page_observations
```

Credentials are accepted only through `CONFLUENCE_BASE_URL` and
`CONFLUENCE_PAT`. Success output contains only fixed boolean checks. Failure
output contains only a fixed category and status.

## Raw path rules

```text
<raw_root>/confluence/restrictions/view/
  <selected_page_id>/<target_page_id>.body

<raw_root>/confluence/attachments/metadata/
  <selected_page_id>/start-<start>_limit-<limit>.json
```

All writes use an exclusive same-directory temporary file, flush, fsync, close,
and atomic replace. Only the current operation's temporary file is cleaned on
failure. A failed replace preserves a prior final artifact.

## Restriction classification

- valid 200 plus no user/group principals: `unrestricted`;
- valid 200 plus at least one observed principal: `restricted`;
- 401, 403, or 404: `unavailable`;
- malformed or unrecognized 200 response: `unavailable`.

Principal identifiers are copied exactly into the internal observation and are
never printed. M6B does not compute inheritance, effective ACL, group expansion,
ACL tags, or ACLRecord.

## Pagination safety

- Initial window is exactly `start=0` and the configured page size.
- Termination occurs only when `_links.next` is absent.
- `size`, result count, and calculated offsets never determine the next window.
- A next link must be a root-relative reference to the exact attachment endpoint
  for the selected page, with exactly one canonical non-negative `start` and one
  canonical positive `limit` query value.
- Absolute/external, wrong-page, wrong-endpoint, fragmented, extra-query,
  repeated, cyclic, or non-advancing links fail closed.
- A required configured maximum-window budget stops traversal before another
  request is made.
- Attachment IDs must be unique within and across windows.
- Download links are never followed and attachment bodies are never requested.

## Verification

The focused CLI tests monkeypatch both opener construction and `urlopen`; all
other M6B tests use fakes at a port or transport seam. No test can accidentally
reach Confluence.

```text
python -m pytest <six focused M6B/transport paths> -q
125 passed in 3.38s

python -m pytest tests/foundation -q
768 passed in 24.80s

python -m pytest tests/shared -q
17 passed in 1.31s

python -m pytest tests/architecture -q
4 passed in 0.16s

git diff --check
PASS (line-ending warnings only on this Windows checkout)
```

Every review commit was also checked from its own clean detached worktree with
`python -m pytest tests/foundation tests/shared tests/architecture -q`:

```text
bed4422  715 passed
23e763e  771 passed
4c9eb7d  784 passed
56e1e71  789 passed
[M6B-F]  789 passed
```

An optional repository-wide `python -m pytest -q` run reached `791 passed` and
then reported 9 pre-existing Indexing async-test failures because this local
environment does not have `pytest-asyncio`. Those tests and that dependency are
outside Foundation/M6B; no Indexing file was changed.

## Known limitations

- The current transport contract accepts absolute-path references, so M6B
  deliberately rejects absolute pagination URLs even if they appear to name the
  same host. The sanitized M6-0 evidence confirms that `_links.next` was followed
  but intentionally does not retain its exact textual URL form; this is a
  controlled-live verification point, and any unsupported form fails closed.
- M6B preserves and normalizes observations only. It intentionally does not emit
  ACLRecord or MediaAsset and does not interpret `body.storage`.
- Retry, rate limiting, checkpoint/resume, and multi-page crawling remain M7.

## Proposed controlled live command

Run only after detached offline approval, on the connected machine, using the
same raw root and page ID whose M6A artifact already exists:

```powershell
$env:CONFLUENCE_BASE_URL = "<https-base-url>"
$env:CONFLUENCE_PAT = "<personal-access-token>"
$env:PYTHONPATH = "src"

python -m knowledgenexus.foundation.cli.collect_confluence_page_observations `
  --page-id "<numeric-page-id>" `
  --raw-root "<same-raw-root-used-by-M6A>" `
  --attachment-page-size 1 `
  --max-attachment-pages 20
```

The page size of 1 intentionally matches the approved M6-0 observation that
exercised multiple attachment windows. The maximum of 20 is an explicit safety
ceiling above the 8 windows observed there.
