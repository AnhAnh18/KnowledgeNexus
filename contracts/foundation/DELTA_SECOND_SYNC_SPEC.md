# Evidence-Bound Delta Second-Sync Inventory

## Status

Version 1.0.0. This contract defines the generation-scoped `delta-inventory.json`
artifact consumed by the W4 second-sync path.

## Binding

The artifact records `run_id`, `generation_id`, `current_selection_identity`,
`accepted_base_dataset_version`, and `current_scope_identity`. These values are
immutable bindings: a classifier or consumer must reject mismatches rather than
silently mixing generations, selections, scopes, or accepted bases.

Every Confluence page in the accepted base and every page in the complete current
selection occurs exactly once. `document_id` is derived from `page_id` using the
canonical Confluence document-ID rule and is never an independent authority.
Removed pages retain the accepted base document's `source_version_last_seen`.
Git records are not valid W4 input.

## Evidence

Pages absent from the complete current selection require a direct page-content
probe. The preserved raw probe records the HTTP status, response byte count, and
SHA-256 of the exact response bytes. Raw evidence is published before the
derived disposition is checkpointed. A disposition is derived only from the
status and approved current scope facts:

- selection membership -> `present`;
- 404 -> `source_deleted` with detail
  `confluence_404_may_mask_access_revoked`;
- 403 -> `access_revoked`;
- 200 plus proven exclusion/out-of-scope ancestry -> `moved_out_of_scope`.

401, exhausted retryable statuses, unexpected statuses, malformed evidence, and
an in-scope 200 missing from a supposedly complete selection fail closed.
Restriction-endpoint 404 remains unavailable and is not page deletion evidence.

## Safety and replay

Writes are atomic, generation-scoped, no-clobber, path-safe, and reject symlink
or reparse traversal. Replay verifies existing bytes and reuses matching
evidence; conflicts fail closed. Active M7 reliability limits govern response
bytes, requests, artifacts, and free disk. CLI output and review summaries are
sanitized and never contain raw bodies, page IDs, URLs, paths, hashes, titles,
principals, or credentials.
