# M5C — Confluence inventory smoke run

Operator runbook for the first live execution of the approved Confluence Data
Center inventory path. Run this on the Confluence-connected machine only.

## 1. What this does

It performs a **read-only page-metadata inventory** of one selected root, using
the approved production components exactly as reviewed:

```
UrllibConfluenceHttpTransport
  -> ConfluenceDataCenterInventoryAdapter
  -> BuildConfluenceInventory
  -> ConfluenceInventoryReportWriter
```

The runner adds no HTTP, CQL, pagination, parsing, normalization, scope, or
report-serialization logic of its own.

## 2. What it does not do

- Issues **`GET` only**, through the M5B-2 adapter. No other endpoint is called.
- Does **not** fetch page bodies, attachments, permissions, restrictions, or
  ACL. Attachment counts are therefore always unknown, never zero.
- Does **not** retry, sleep, rate-limit, checkpoint, or resume. Any failure
  stops the run.
- Does **not** export a snapshot, create records, index, or embed.

## 3. Scope for the first run

Use the **same small test root** exercised during M5B-0 (8 descendants,
including one nested descendant). Do **not** point the first run at the large
production space root.

If that root is unavailable, pick another known non-sensitive root with **at
most 20 descendants**.

The first-run configuration is:

```
page_size        = 2
max_search_pages = 10
```

This deliberately exercises roughly four pagination windows while staying under
the adapter's safety budget. `2 x 10` allows at most 20 descendants: if the run
exits with category `pagination_limit`, the chosen root is **too large for a
smoke run**. Select a smaller root. Do **not** silently raise
`--max-search-pages` and do not probe the large production root.

## 4. Required environment

Two variables, set in the shell only. The token is **never** accepted on the
command line and is never printed, logged, or written to any output file.

| Variable | Meaning |
|---|---|
| `CONFLUENCE_BASE_URL` | HTTPS base URL, including any context path. No user-info, query, or fragment. |
| `CONFLUENCE_PAT` | Personal access token with read access to the selected space. |

The runner never loads `.env` automatically and never persists these values.

## 5. Output directory

`--output-dir` must:

- be **outside the repository working tree**;
- already exist;
- be a directory;
- be **empty** before the run.

The runner refuses anything else. It never writes reports inside the repository
and never modifies `.gitignore`.

## 6. Run it

Replace every placeholder. Do not paste real values into any committed file.

```powershell
$env:CONFLUENCE_BASE_URL = "<https-base-url>"
$env:CONFLUENCE_PAT      = "<personal-access-token>"

New-Item -ItemType Directory -Force "<output-dir-outside-repo>"

cd "<repository-root>"
$env:PYTHONPATH = "src"

python -m knowledgenexus.foundation.cli.confluence_inventory_smoke `
  --source-id "<source-id>" `
  --space-key "<space-key>" `
  --root-page-id "<numeric-root-page-id>" `
  --page-size 2 `
  --max-search-pages 10 `
  --output-dir "<output-dir-outside-repo>"
```

Add one flag per excluded subtree, if any:

```powershell
  --exclude-subtree-page-id "<numeric-page-id>"
```

## 7. Success

Exit code `0`, and the output directory contains **exactly three** files:

| File | Contents |
|---|---|
| `pages_inventory.jsonl` | Real inventory metadata. **Stays on this machine.** |
| `inventory_report.csv` | Real inventory metadata. **Stays on this machine.** |
| `m5c_smoke_summary.json` | Counts, booleans, limits, and report hashes only. |

The summary is also printed to stdout. It contains no source ID, space key,
page ID, title, path, host, URL, CQL, header, or token.

## 8. Failure

Exit code is non-zero and one sanitized JSON object is written to stderr:

```json
{ "status": "failed", "category": "<category>", "cleanup_incomplete": false }
```

No summary file is written. `m5c_smoke_summary.json` is **success-only** — its
presence is itself the evidence that the run passed.

| Exit | Category | Usual meaning |
|---|---|---|
| 2 | `configuration` | Missing/invalid env or arguments. |
| 3 | `output_directory` | Output dir missing, not a directory, non-empty, or inside the repo. |
| 4 | `connection` | The host could not be reached. |
| 5 | `authentication_or_http` | Non-2xx status, or an HTML login/SSO page instead of JSON. |
| 6 | `response_contract` | The response did not satisfy the approved contract. |
| 7 | `pagination_limit` | Budget exhausted — the root is too large for a smoke run. |
| 8 | `report_write` | Reports could not be written. |
| 9 | `report_verification` | Written reports failed verification. |
| 1 | `unexpected` | Anything else. |

Failure output never contains the host, URL, space key, page IDs, titles,
paths, CQL, credentials, headers, payloads, or raw exception text. A mistyped
flag — including `--pat <token>` — is rejected without echoing the arguments.

**Inspect the output directory after any failure before reusing it.** Files this
run created are removed, but a `report_verification` failure can mean the report
writer left its own `.<name>.tmp` files behind; those hold a second copy of real
inventory metadata and are not deleted here, because this runner never removes
entries it did not create. If `cleanup_incomplete` is `true`, even files this run
created could not be removed.

## 9. Root labels are not authoritative

M5C requests `expand=space,version` for the selected root. It does **not**
request root labels.

- The root row's **empty labels cell is not authoritative**. It means
  *unknown / not observed*, not *confirmed no labels*.
- Do **not** use root labels to choose exclude-subtree configuration.
- Exclusions are **explicit page IDs** chosen from the known tree.
- **Descendant** labels are different: they come from the confirmed
  search-response metadata and are trustworthy.

The summary states this explicitly via `root_labels_requested: false` and
`root_labels_interpretation: "unknown_not_requested"`.

## 10. What may leave this machine

Only:

1. `m5c_smoke_summary.json`;
2. a **manually sanitized** completion notice you have read in full.

`pages_inventory.jsonl` and `inventory_report.csv` contain real page titles,
paths, and identifiers. They **must remain on this machine**. Do not paste them
into a chat, ticket, commit, or any other tool.

## 11. Clear the environment afterwards

```powershell
Remove-Item Env:\CONFLUENCE_PAT
Remove-Item Env:\CONFLUENCE_BASE_URL
Remove-Item Env:\PYTHONPATH
```

Close the shell. The token lives only in that process; nothing on disk holds it.

## 12. Verify no live data entered the repository

From the repository root:

```powershell
git status --porcelain
```

Expect **no** entry for `pages_inventory.jsonl`, `inventory_report.csv`,
`m5c_smoke_summary.json`, or any path under your output directory. If any
appears, the output directory was inside the repository — move it out and do
not commit. Confirm with:

```powershell
git diff --cached --name-only
```
