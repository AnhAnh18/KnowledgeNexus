# M6C One-Page Confluence Normalization - Implementation Summary

## Status

- `M6C_BASE_COMMIT`: `97a6747` (`[M6B-G]` durable closeout).
- Candidate stack:
  - `566394a` `[M6C-A]` trusted raw-page extraction boundary and tests;
  - `3b2c7da` `[M6C-B]` deterministic XHTML/macro processor and tests;
  - `84afd0c` `[M6C-C]` canonical-document use case, offline CLI, and tests;
  - `[M6C-D]` production-store integration proof and this state registration.
- Production review head: the `[M6C-D]` commit containing this summary.
- Detached reviewer: Claude, Extra High.
- Detached review: pending.
- Local real-artifact acceptance: pending until detached review passes.
- No network request was performed. M6D was not started.

## Implemented boundary

The use case reads exactly one preserved M6A artifact through
`RawPageReadPort`. A Data Center source mapper validates the UTF-8 JSON
envelope, numeric identity, page type, title, space key, version, update time,
and `body.storage` shape. It passes only trusted values and the storage fragment
to the processor.

The pure-in-effect processor uses `xml.etree.ElementTree` with a deterministic
namespace wrapper. It rejects DOCTYPE and entity declarations before parsing,
does not resolve external entities, rejects malformed fragments, and never
embeds raw XHTML in an exception or warning.

Final text normalization is local to M6C and follows the active chunking
contract: Unicode NFC, LF line endings, stripped trailing whitespace, one blank
line between blocks, and no leading/trailing blank lines. The older generic M2
`TextNormalizationRules` behavior was not changed because doing so would alter
unrelated golden hashes.

## Element and macro behavior

Supported baseline output covers headings, paragraphs, line/horizontal breaks,
strong/emphasis, inline and block code, blockquotes, nested ordered/unordered
lists, ordinary links, and tables. Rectangular tables become Markdown tables.
Span/irregular tables retain meaningful cell text in source order with a
`complex_table_fallback` warning.

Handled macro policy:

- code: optional safe language/title and a fence longer than embedded backtick
  runs;
- expand/excerpt: body text retained; expand title is bold;
- include/excerpt-include: `[included-page]` without a fetch;
- drawio variants: `[diagram]`;
- jira: a syntactically valid observed issue key only, otherwise a generic
  placeholder;
- toc: dropped and counted;
- info/note/warning/tip/panel: stable blockquote prefix and body;
- Confluence images and attachment links: generic media placeholders;
- unknown rich macro: `[macro:name]` plus retained body;
- unknown bodyless macro: `[macro:name omitted]`.

No MediaAsset or RelationRecord is created.

## Result and canonical mapping

The focused result contains normalized text, one plain canonical-document dict,
one counters dict, and source-ordered warning dicts. Warnings contain only a
fixed code, sanitized name, and ordinal. Counters contain sorted handled and
unhandled macro counts plus `toc_dropped`, `media_placeholders`,
`unsupported_elements`, and `complex_tables`.

Canonical mapping uses the existing builder and ID rules:

- `document_id = confluence:page:<page_id>`;
- `source_system = confluence`, `source_type = wiki_page`;
- trusted title, space key, page id, `str(version.number)`, and `version.when`;
- deterministic `acl_id`, without an ACLRecord;
- empty Jira/relation ID lists;
- explicit caller-provided RFC 3339 `crawled_at`;
- content hash over the exact final normalized body;
- empty metadata and no unknown top-level fields.

The CLI validates the result with `FoundationSchemaValidator`. It prints only a
fixed success/failure category and aggregate counts; no body, identity, title,
path, URL, filename, or full hash is emitted. It does not persist normalized
content.

## Verification

```text
python -m pytest \
  tests/foundation/infrastructure/processors \
  tests/foundation/application/use_cases/test_normalize_confluence_page.py \
  tests/foundation/cli/test_normalize_confluence_page_cli.py \
  tests/foundation/integration/test_normalize_confluence_page_e2e.py \
  tests/architecture -q
-> 93 passed in 2.26s

python -m pytest tests/foundation tests/shared tests/architecture -q
-> 898 passed in 20.57s

git diff --check
-> exit 0
```

All tests are offline. CLI and integration tests replace urllib network entry
points with functions that fail the test if called.

## Proposed local real-artifact command

Run only after detached offline approval, from a checkout containing the
reviewed production head, against the retained M6A raw root:

```powershell
$env:PYTHONPATH = "src"
py -3.13 -m knowledgenexus.foundation.cli.normalize_confluence_page `
  --page-id "<numeric-page-id>" `
  --raw-root "<same-raw-root-used-by-M6A>" `
  --crawled-at "<explicit-rfc3339-utc-timestamp>"
```

The command is offline, writes no normalized artifact, and prints only a
sanitized summary. Do not place the real page identity, path, title, content, or
hash in review documentation.

## Deferred limitations

- M6C is not a complete HTML or complex-table engine; M8 owns production-depth
  rendering and table semantics.
- Media and included-page references remain generic placeholders; no resolution
  or attachment-body access occurs.
- Unknown safe elements/macros use deterministic fallbacks and warnings rather
  than a plugin registry.
- M6C does not use M6B restrictions to materialize ACL semantics. M6F owns that
  deny-safe step.
- Chunking, relations, export, sync, and scale/reliability remain later tasks.
