# Confluence URL text demo

This operator is a bounded demo path for producing an Indexing packet from one
Confluence root and its descendants. It is not the W5 controlled acceptance
runbook and it does not replace the authoritative full-snapshot workflow.

## Output and scope

The operator crawls the selected root subtree, preserves immutable raw page
evidence, normalizes and chunks text, and atomically publishes:

```text
<output-root>/
|-- LATEST.txt
`-- versions/confluence-<run-id>/
    |-- documents.jsonl
    |-- chunks.jsonl
    |-- media_assets.jsonl
    `-- packet_summary.json
```

Indexing consumes `documents.jsonl` and `chunks.jsonl`. All chunks retain the
deny-safe `restricted:unresolved` ACL tag. This demo does not make content
public and does not write directly to Qdrant or SQLite.

## Prerequisites

Run from the repository root in PowerShell. Set credentials and the exact local
BGE-M3 tokenizer bundle in the current process environment:

```powershell
$env:CONFLUENCE_PAT = '<set privately>'
$env:KN_TOKENIZER_ASSETS_DIR = 'C:\path\to\pinned-bge-m3-assets'
$env:KN_PYTHON_EXECUTABLE = 'C:\path\to\python.exe' # optional
```

Never place the PAT in a command argument, committed file, packet, or log.
Use an absolute output path whose parent already exists. A new crawl must use a
new, empty output root.

Prefer a canonical URL carrying both the space and numeric page identity:

```text
https://<host>/spaces/<SPACE>/pages/<PAGE_ID>
```

The explicit `pages/viewpage.action?pageId=...&spaceKey=...` form is also
supported. Some `/x/...` links require a live redirect whose target shape is
not supported; use the canonical URL when that produces `url_shape`.

## Strict run

Use strict mode when every selected page must be processed and Draw.io evidence
must be captured:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File '.\scripts\run-confluence-text-demo.ps1' `
  -Url '<CANONICAL-CONFLUENCE-URL>' `
  -OutputRoot 'D:\KnowledgeNexusData\Demo\<fresh-name>' `
  -MaxPages 5000
```

`MaxPages` is a hard safety ceiling, not a sampling request. It must be at least
the discovered number of pages and cannot exceed 5,000.

## Explicit partial text demo

The approved chunker intentionally rejects a table row that cannot fit under
the 1,000-token hard maximum. For a time-critical text demo, explicitly enable
best-effort processing:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File '.\scripts\run-confluence-text-demo.ps1' `
  -Url '<CANONICAL-CONFLUENCE-URL>' `
  -OutputRoot 'D:\KnowledgeNexusData\Demo\<existing-or-fresh-name>' `
  -MaxPages 5000 `
  -AllowPartialProcessing
```

This mode:

- processes pages independently and retains all successful documents/chunks;
- records only aggregate failure categories and counts;
- publishes `processing_status: partial` even when all text pages succeed;
- writes an empty `media_assets.jsonl` and does not capture Draw.io;
- never truncates or rewrites an oversized table row;
- never calls the result a complete/full snapshot.

Inspect `packet_summary.json` before handing the packet to Indexing. The
expected fields include `requested_pages`, `succeeded_pages`, `failed_pages`,
`failure_categories`, `processing_mode`, and `drawio_status`.

## Resume and URL identity

Reuse the exact same `OutputRoot` and `MaxPages` after a stopped or failed run.
Inventory and acknowledged raw pages are replayed from durable state; do not
delete the `.state` or `.raw` directories.

Resume is bound to the normalized resource identity, not the literal URL text:

```text
(base_url, space_key, root_page_id, max_pages)
```

Therefore canonical and `viewpage.action` URLs that resolve to the same tuple
are compatible. A different host/context, space, root page, or page ceiling
fails closed as `context_binding`. A short URL that cannot itself be resolved
fails earlier as `url_shape`; that is a URL-resolution limitation, not evidence
that the stored crawl belongs to a different page.

When a short URL fails during resume, reconstruct the canonical URL from the
existing local context without printing its values:

```powershell
$root = 'D:\KnowledgeNexusData\Demo\<existing-name>'
$context = Get-Content "$root\text-snapshot-context.json" -Raw |
  ConvertFrom-Json
$canonicalUrl = (
  "$($context.base_url)/spaces/$($context.space_key)/pages/$($context.root_page_id)"
)

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File '.\scripts\run-confluence-text-demo.ps1' `
  -Url $canonicalUrl `
  -OutputRoot $root `
  -MaxPages $context.max_pages `
  -AllowPartialProcessing
```

Once a packet is published, subsequent calls verify and return the frozen
packet status. A partial packet remains partial on replay.

## Failure handling

- Preserve the output root after any failure; do not delete valid checkpoint or
  raw artifacts.
- `capture_incomplete` means capture did not reach its terminal checkpoint.
- `chunking_failed` in strict mode requires offline diagnosis.
- `unsplittable_table_row` may use explicit partial mode for a demo only; its
  production, lossless, versioned remediation remains open.
- No `LATEST.txt` means no packet has been published.
- Do not run two operators against the same output root concurrently.
