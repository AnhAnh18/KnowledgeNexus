# M5B-0 Confluence Inventory Probe Runbook

This bundle collects a small, sanitized API-confirmation packet. It is a
diagnostic only: it does not import KnowledgeNexus, does not implement a
production adapter, and performs `GET` requests only.

## 1. Copy the standalone bundle

Preserve this layout on the Confluence-connected machine:

```text
C:\Temp\knowledge-nexus-confluence-probe\
|-- tools\
|   |-- collect_confluence_inventory_packet.py
|   |-- confluence_request_profile.json
|   |-- confluence_request_profile.template.json
|   `-- RUNBOOK_M5B0_CONFLUENCE_PROBE.md
`-- tests\
    `-- test_collect_confluence_inventory_packet.py
```

Requirements: Python 3.11 or newer and the Python standard library. The current
connected machine uses Python 3.13.2. Do not copy repository credentials,
`.env` files, or generated packet data into this bundle.

## 2. Confirm one working request family

On the connected machine, inspect the existing working code before preparing
the profile:

- `Tool_TRreport/tr_wiki_maker.py`;
- uses of `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT`;
- existing Confluence request helpers and sanitized examples;
- the installed Confluence deployment/version, if already documented.

Do not print environment-variable values, request headers, or response bodies.
Do not try candidate endpoint lists. Confirm exactly one root metadata request,
one root-scoped inventory/descendants request, its authentication scheme, and
its pagination mechanism. If these cannot be established from known working
code or an administrator-provided request, stop; the probe intentionally has
no guessed Cloud or Data Center defaults.

For the current Data Center evidence, the first sanitized packet proved that
`parent` on `/rest/api/content` was ignored and returned pages outside the
selected root. Do not reuse that request. The second packet confirmed the
already-existing Tool_TRreport CQL shape on `/rest/api/search` and exposed
numeric `start`, `limit`, `size`, and `totalSize` fields, but no usable
`/_links/next`. The current profile therefore uses those confirmed numeric
fields with all three immutable selectors (`space`, `ancestor`, `type=page`)
and expands only `content.ancestors`, `content.space`, `content.version`, and
`content.metadata.labels`. One final small diagnostic must confirm multi-page
advancement and these metadata shapes before a production adapter is built.

## 3. Validate the non-secret request profile

For the current follow-up run, use the supplied
`tools\confluence_request_profile.json` without modifying it. The template is
retained only for a future deployment whose confirmed request family differs.
If that ever happens, edit only a copied profile and follow these constraints:

- Set `deployment` to `cloud` or `data-center` from evidence.
- Set `api_family` to a non-sensitive API family/base-path description.
- Set `auth_scheme` to `bearer_pat` or `basic_username_pat`.
- Keep runtime values as `{root_page_id}`, `{space_key}`, and `{page_size}`.
- Use exact origin-absolute paths. For an installation under `/wiki`, include
  `/wiki` in each `path_template`.
- Represent query parameters as ordered `[name, value]` pairs. Delete the
  example pair if it is not part of the confirmed request.
- The inventory template must contain `{root_page_id}` and `{page_size}`.
- Do not add body expansions. The validator rejects an explicit `body` request.
- Do not configure attachment, comment, restriction, ACL/permission, rendered
  HTML, download, or export routes/expansions. The validator rejects them,
  including percent-encoded spellings.
- For `json_next`, fill `next_pointer` with an RFC 6901 JSON pointer such as the
  pointer actually observed in known evidence. Use this kind only when the
  pointer contains a relative/absolute next URL, not a bare cursor. Unused
  start/limit fields are ignored. Set `mutable_query_parameters` to only the
  cursor/page query names that URL can add or change; use `[]` if none change.
- Only pagination-position keys such as a confirmed `start`/cursor may be
  mutable. Never add `type`, `status`, `space`, `parent`, `ancestor`, `cql`,
  `limit`, `expand`, or another scope/page-size selector. Immutable query pairs
  may be reordered by Confluence; the probe compares their decoded pair counts
  without relying on order and still rejects every name/value/count change.
- For `link_header`, set `mutable_query_parameters` the same way. A next URL is
  accepted only when its path and all non-pagination query pairs remain exactly
  equal to the initial inventory request.
- For `cursor_value`, fill `next_pointer` with the JSON pointer to the bare
  opaque cursor and `cursor_query_parameter` with the confirmed request query
  name. The script only inserts that returned value into that one query key.
- For `start_limit`, fill both query parameter names and all four response JSON
  pointers. Replace `inventory_request.query` with both pairs from
  `_start_limit_inventory_query_example`: the initial start value must be a
  non-negative integer (normally `0`), the limit value must be `{page_size}`,
  and both names must exactly match the pagination names. The only supported
  terminal rule is `start_plus_size_gte_total`.

Never place the hostname, real root ID, real space key, username/email, PAT,
cookie, or Authorization value in the profile.

Validate the profile offline; this command reads no credentials and makes zero
network requests:

```powershell
py -3.13 .\tools\collect_confluence_inventory_packet.py `
  --request-profile .\tools\confluence_request_profile.json `
  --validate-profile-only
```

Expected message:

```text
OK: request profile is valid; no network request was made.
```

## 4. Run the offline test suite

From the bundle root:

```powershell
py -3.13 -m unittest discover -s .\tests `
  -p 'test_collect_confluence_inventory_packet.py' -v
```

The tests use fake responses and temporary directories only. They make no
network requests. Expected result for this follow-up bundle:

```text
Ran 58 tests
OK
```

## 5. Run one live diagnostic

Use a new output directory. Do not pass credentials on the command line. In an
interactive PowerShell session, leave `CONFLUENCE_PAT` unset so the script uses
a hidden `getpass` prompt. If `CONFLUENCE_BASE_URL` is unset, the script prompts
for it without saving it. `basic_username_pat` also prompts for the username
when `CONFLUENCE_USERNAME` is unset.

The command below includes `--prompt-scan-identities`. It uses hidden input for
optional usernames, emails, and account IDs that must not occur in the packet;
press Enter when there are none. Do not put those values in CLI arguments.

Run with placeholders replaced locally:

```powershell
py -3.13 .\tools\collect_confluence_inventory_packet.py `
  --request-profile .\tools\confluence_request_profile.json `
  --space-key '<SPACE_KEY>' `
  --root-page-id '<ROOT_PAGE_ID>' `
  --page-size 2 `
  --max-pages 4 `
  --timeout-seconds 30 `
  --prompt-scan-identities `
  --output-dir 'C:\Temp\knowledge-nexus-confluence-packet-<YYYYMMDD-HHMMSS>'
```

The script makes one root `GET`, then between one and four inventory `GET`s. It
does not redirect, retry, load `.env`, fetch attachments, or issue per-page
enrichment requests. It follows only the configured mechanism. For the current
`start_limit` profile, it advances only from the confirmed response integers
and checks each response window against the request. Cross-origin next URLs are
rejected.

Environment variables supported by design:

- `CONFLUENCE_BASE_URL`: optional instead of the interactive URL prompt;
- `CONFLUENCE_PAT`: optional instead of hidden `getpass` input;
- `CONFLUENCE_USERNAME`: required only for non-interactive basic authentication;
- `CONFLUENCE_SCAN_IDENTITIES`: optional comma-separated leak-scan terms.

Clear process-local values after the run:

```powershell
Remove-Item Env:CONFLUENCE_PAT -ErrorAction SilentlyContinue
Remove-Item Env:CONFLUENCE_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:CONFLUENCE_SCAN_IDENTITIES -ErrorAction SilentlyContinue
Remove-Item Env:CONFLUENCE_BASE_URL -ErrorAction SilentlyContinue
```

The last command should be used only when `CONFLUENCE_BASE_URL` was set solely
for this probe.

## 6. Expected output tree

Only observed sanitized artifacts are created:

```text
C:\Temp\knowledge-nexus-confluence-packet-<YYYYMMDD-HHMMSS>\
|-- confluence_api_profile.md
|-- confluence_request_trace.md
|-- root_page_response.sanitized.json
|-- descendants_page_1.sanitized.json
|-- descendants_page_2.sanitized.json       # only when observed
|-- descendants_last_page.sanitized.json    # terminal page > page 2 only
`-- sanitization_report.md
```

If the safety cap is reached while a next page exists, no terminal-page claim
or fake last-page file is created and the reports say
`pagination_truncated: true`.

## 7. Manual sanitization verification

Before copying anything back, verify every item below on the connected machine:

- The directory contains only the seven allowed names above; page 2 and last
  page may be absent according to observation.
- There are no raw-response, log, HTML, temporary, `.env`, profile, or credential
  files in the packet directory.
- Confirm the successful run completed its built-in in-memory scan for the real
  hostname, full base URL, exact PAT, and the hidden identity terms. Never put a
  PAT literal in `rg`, `Select-String`, Cline, or shell history.
- Run the independent verifier below. It prompts for the base URL, PAT, and scan
  identities again; PAT and identities use hidden input and it makes no network
  requests:

  ```powershell
  py -3.13 .\tools\collect_confluence_inventory_packet.py `
    --request-profile .\tools\confluence_request_profile.json `
    --verify-packet-only `
    --prompt-scan-identities `
    --output-dir 'C:\Temp\knowledge-nexus-confluence-packet-<YYYYMMDD-HHMMSS>'
  ```

  Expected message: `OK: existing packet passed the sanitized leak scan; no
  network request was made.`
- Search for `Authorization:`, `Bearer ` followed by credential material,
  `Cookie:`, and `Set-Cookie:`; every search returns zero matches.
- Real page titles and body phrases are absent. Body value leaves read
  `<SANITIZED_BODY>` when a body was unavoidable in the known response.
- Absolute URLs use `<CONFLUENCE_HOST>`; relative URLs remain relative. Opaque
  cursor values are synthetic while their field/query position remains intact.
- Open each `.json` file with a JSON parser. Object/list shape, nullability,
  scalar types, ancestor order, timestamp format, and version-number type are
  retained.
- The requested root has one stable synthetic ID everywhere it occurs. Integer
  IDs remain integers and string IDs remain strings.
- Every request in `confluence_request_trace.md` is `GET`; its count is one root
  request plus the number of observed inventory response pages.
- `sanitization_report.md` accurately states whether pagination was truncated.

Copy back only the files inside the sanitized packet directory. Do not copy
back `confluence_request_profile.json`, environment values, terminal history,
or any captured raw response.

## 8. Failure handling and exit codes

The script writes nothing until all responses are sanitized and validated. It
requires a new or empty output directory and never overwrites an existing file.
Same-directory temporary files are always removed. If a later publication step
fails, already-published sanitized files are deliberately retained because a
path-based rollback could race and delete another writer's replacement; the
run is not successful, the partial directory must not be copied back, and the
next run must use a new output directory.

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid CLI or request profile |
| 3 | Missing/invalid credential input |
| 4 | Unsafe or unusable output location |
| 10 | Network/TLS/timeout failure |
| 11 | Sanitized HTTP failure |
| 12 | Invalid/oversized/non-JSON response |
| 13 | Invalid, stalled, repeated, or cross-origin pagination |
| 14 | Sanitization or packet validation failure |
| 70 | Unexpected failure; details withheld |

On failure, do not paste secrets or raw server responses into a ticket. Record
only the exit code, sanitized message, confirmed request-profile kind, and the
step that failed.
