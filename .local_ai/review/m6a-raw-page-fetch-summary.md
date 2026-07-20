# M6A Raw Page Fetch Implementation Summary

> Implementation and review record. Codex independently reviewed the original
> stack and the focused review fix through `REVIEW_HEAD` `5542311`.
>
> No production live run was performed on this checkout. The operator later
> completed the controlled live run on the independent target repository; its
> sanitized result is registered in `m6a-live-evidence-summary.md`. No production
> raw artifact was committed, staged, attached to this summary, or included in
> the review range.

## Status

- Offline implementation verdict: **Approve**.
- Independently reviewed production range: `0948252..5542311`.
- Controlled production live run: **PASS** at independent target production
  head `e2823f9ca492becb17d6b2352aeada6bdf85d3ae`.
- Live acceptance gate: **passed; sanitized evidence registered**.
- Overall task status: **complete**; the repository owner accepted the
  documentation/state closeout.
- `M6A_FINAL_HEAD` is the controlled-live closeout commit containing this state.
- M6B may begin after this closeout commit is created.

## Task

Fetch and preserve exactly one raw production Confluence page:
one page GET -> minimal verification -> exact raw-byte preservation -> SHA-256 ->
deterministic path -> atomic replacement.

## Review range

- `BASE_COMMIT` (M6A stack base, after the M6-0 evidence sync): `0948252`
- Stack (keep the lettered commits per repository convention):
  - `cffa3f1` `[M6A-A]` raw-byte transport capability + tests
  - `de389ec` `[M6A-B]` deterministic atomic raw page store + tests
  - `9ce4590` `[M6A-C]` page adapter + use case + operator entrypoint + tests
  - `a8623d4` `[M6A-D]` end-to-end offline regression test
  - `5542311` `[M6A-E]` review fix: move fetch/store behind foundation ports and
    add the `response_size_limit` category
  - `[M6A-F]` documentation closeout (this commit; no production-code changes)

## Detached review record

- Initial review range: `0948252..a8623d4`.
- Initial verdict: `Changes required`.
- Accepted findings: one P2 and three P3 findings recorded below.
- Focused fix range: `a8623d4..5542311`.
- Focused fix-review verdict: `Approve`.
- Unresolved P0/P1 findings: none.
- Unresolved accepted P2 findings: none.
- The documentation closeout is outside the independently reviewed production
  range and does not change production source or tests.

## Round 1 review fixes (Codex)

- **P2 (Clean Architecture)** — `FetchRawConfluencePage` imported concrete
  infrastructure, the only use case doing so. Fixed in `[M6A-E]`: added
  `foundation.ports.ConfluencePageFetchPort` and `RawPageStorePort` with
  sanitized port-level errors, moved `RawPageArtifact` to
  `foundation.domain.models`, and pointed the use case at ports + domain only.
  A `tests/architecture` import-boundary test now guards every use case.
- **P3 (size category)** — the original summary incorrectly said an oversized
  response produced `store`, while the implementation mapped it to `http`.
  `[M6A-E]` makes the operational result explicit: a transport
  `ConfluenceHttpResponseTooLargeError` and a
  `ConfluencePageTooLargeError` port error yield the distinct
  `response_size_limit` category (CLI exit 9). This is not decision 4A;
  decision 4A governs only the confirmed endpoint and expand shape.
- **P3 (unicode)** — added a byte-fidelity test over real multibyte UTF-8
  (`café`, `世界`) alongside an escaped sequence.
- **P3 (durable docs)** — reconciled the roadmap section with its table row.
- Review each commit directly (`git show <sha>`); the independently reviewed
  production range is `0948252..5542311`.

## Locked decisions applied

- **1A** transport `get_bytes`: added additively to the `ConfluenceHttpTransport`
  protocol and `UrllibConfluenceHttpTransport`. A shared, guarded
  `_read_response_bytes` primitive is extracted so `get_json` keeps identical
  behaviour (HTTPS, redirect refusal, status, JSON content-type, injectable size
  limit); only the trailing `json.loads` is omitted for `get_bytes`. No separate
  transport, no raw HTTP in the page adapter. Regression tests prove `get_json`
  still parses from the same bytes `get_bytes` returns raw.
- **2A** review stack `[M6A-A..E]`, lettered commits kept (squash not requested).
- **3A** `--raw-root` optional, default `data/raw` (gitignored, Foundation
  internal); path `<raw_root>/confluence/pages/<page_id>.json`; no title,
  timestamp, UUID, or version in the path; resolved target confirmed under the
  resolved root.
- **4A** endpoint and expand are confirmed by approved M6-0, not inferred. Test
  fixtures are synthetic and labelled as such; no committed real-shape fixture.

## Behaviour

- Exact page request: `GET /rest/api/content/{page_id}?expand=body.storage,space,version,ancestors,metadata.labels`.
- Raw hash: `raw_sha256 = sha256(exact_persisted_bytes).hexdigest()` (the text
  `ContentHasher` is not used).
- Deterministic path: `<raw_root>/confluence/pages/<page_id>.json`, replaceable.
- Atomic replacement: exclusive same-directory temp, write exact bytes, flush,
  fsync, close, `os.replace`; temp cleaned on failure; a prior final file is left
  byte-identical; no partial final file is exposed; unrelated entries untouched.
- Minimal verification before publication: successful HTTP (2xx or the transport
  raises), valid JSON, top-level object, `str(response id) == requested id`. No
  `body.storage` normalization, no `CanonicalDocument` mapping.
- Sanitized failure categories, per stage: `invalid_page_id`, `http`,
  `response_size_limit`, `malformed_json`, `non_object_json`, `identity_mismatch`,
  `store`, plus CLI `configuration` and `unexpected`. No page id, host, title,
  or body appears in any exception message, log, or CLI output.

## Notes for the reviewer

- The numeric page-id rule is centralized in a new domain rule
  `foundation/domain/rules/confluence_page_id.py`, shared by the raw store and
  the page adapter. The approved inventory adapter (`a2fe824`) is intentionally
  left untouched; its private `_ASCII_PAGE_ID` is the one remaining copy of the
  same rule, not refactored to avoid editing approved code.
- The 8 MB `max_response_bytes` guard stays enforced and injectable via transport
  construction / the CLI `--max-response-bytes`. It is never auto-raised; a page
  over the limit fails closed and stores nothing.
- The CLI test file uses a unique basename (`_cli`) because the test tree has no
  package `__init__.py` and pytest would otherwise collide with the use-case test
  of the same concept.

## Verification

```text
C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/architecture tests/foundation/infrastructure/confluence/test_confluence_http_transport.py tests/foundation/infrastructure/raw_store tests/foundation/infrastructure/confluence/test_confluence_data_center_page_adapter.py tests/foundation/application/use_cases/test_fetch_raw_confluence_page.py tests/foundation/cli/test_fetch_raw_confluence_page_cli.py tests/foundation/integration/test_fetch_raw_confluence_page_e2e.py -q
110 passed

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/foundation -q
689 passed

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/shared -q
17 passed

C:\Users\SPen\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/architecture -q
3 passed

git diff --check   -> exit 0 (clean)

python -m knowledgenexus.foundation.cli.fetch_raw_confluence_page --help   -> usage resolves
python -m ...fetch_raw_confluence_page --page-id 1000 --raw-root <tmp> (no env) -> {"category":"configuration","status":"failed"}, exit 2
```

No `data/raw` directory was created in the repository; tests write only under
`tmp_path`.

## Executed operator command shape (not performed from this checkout)

On the Confluence-connected machine, with credentials in the environment only:

```powershell
$env:CONFLUENCE_BASE_URL = "<https-base-url>"
$env:CONFLUENCE_PAT      = "<personal-access-token>"
cd "<repository-root>"
$env:PYTHONPATH = "src"

python -m knowledgenexus.foundation.cli.fetch_raw_confluence_page `
  --page-id "<numeric-page-id>" `
  --raw-root data/raw
```

The operator reported exit code 0 and exactly these success booleans:

- `method_get=true`
- `status_success=true`
- `json_valid=true`
- `identity_match=true`
- `artifact_written=true`
- `hash_verified=true`
- `temporary_cleanup=true`

No page ID, title, hostname, raw path, full hash, or raw body was included in the
sanitized completion notice. The store's deterministic relative convention is
`confluence/pages/<page_id>.json`; the operator's raw-root location is not
registered, and the artifact must not be committed. A page over the size limit
fails closed with category
`response_size_limit` (CLI exit 9, from the transport size guard); raising the
limit is an explicit `--max-response-bytes` operator choice, not an automatic
retry.

## Boundary

No restriction/attachment/inventory/descendant call; no ACL interpretation, no
XHTML parsing, no normalization, no chunking, no relation/Jira, no sync/tombstone,
no export, no embedding/retrieval/chat; no live run from this checkout; M6B not
started. No third-party package or external runtime dependency was added.
