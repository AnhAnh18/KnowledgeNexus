# Evidence-Bound Delta Second-Sync Inventory

## Status

Version 1.0.0. This contract defines the generation-scoped `delta-inventory.json`
artifact consumed by the W4 second-sync path.

The canonical envelope fields, in order, are:

1. `format_version` (exactly `1.0.0`);
2. `run_id` and `generation_id` (canonical lowercase UUIDv4 values, equal to
   each other); `current_selection_identity` and `current_scope_identity`
   (exactly 64 lowercase hexadecimal SHA-256 characters); and
   `accepted_base_dataset_version` (non-empty opaque dataset version);
3. `entries` (sorted by `document_id`, unique);
4. `metrics` with exactly `present_count`, `source_deleted_count`,
   `access_revoked_count`, and `moved_out_of_scope_count`.

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

The envelope is rejected when run and generation identities differ, when either
identity has a non-canonical UUIDv4 shape, or when either selection/scope
identity is not a lowercase SHA-256 digest. These are normative field rules,
not adapter-only conventions.

Each observation has exactly `page_id`, `http_status`, `ancestor_page_ids`,
`response_byte_count`, `response_sha256`, and `source_version_last_seen`.
Every page ID, ancestor ID, include-root ID, and exclusion ID must satisfy the
strict ASCII-decimal Confluence page-ID rule. Scope facts are derived from those
IDs: the page is under an include root when its ID or an ancestor is an include
root; direct and ancestor exclusions are derived similarly. Callers cannot submit
precomputed scope booleans.

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

Allowed status/state combinations are therefore `200/present` only for selected
pages, `404/source_deleted`, `403/access_revoked`, and
`200/moved_out_of_scope` only when derived scope facts prove exclusion or that
the page is no longer under an include root. A 404 entry must carry the exact
detail `confluence_404_may_mask_access_revoked`; other states have no detail.
Each removed entry carries the prior source version. Only these four W4 states
are valid in an envelope or classifier result: `present`, `source_deleted`,
`access_revoked`, and `moved_out_of_scope`. `present` has null source version
and null detail. `source_deleted` requires the prior source version and exact
404 ambiguity detail. `access_revoked` and `moved_out_of_scope` require the
prior source version and null detail. Metrics equal the exact counts of emitted
entries and `total_count` equals `len(entries)`; no counter may be negative,
boolean, hidden, or inconsistent.

Every envelope document ID must be `confluence:page:<ASCII-decimal-page-id>`
and must re-derive from that suffix through the canonical document-ID rule.

401, exhausted retryable statuses, unexpected statuses, malformed evidence, and
an in-scope 200 missing from a supposedly complete selection fail closed.
Restriction-endpoint 404 remains unavailable and is not page deletion evidence.

The sanitized failure vocabulary is: `invalid_input`, `invalid_prior_snapshot`,
`invalid_selection_scope`, `invalid_observation`, `incomplete_evidence`,
`inventory_inconsistent`, `invalid_result`, and `internal_failure`.

## Safety and replay

Writes are atomic, generation-scoped, no-clobber, path-safe, and reject symlink
or reparse traversal. Replay verifies existing bytes and reuses matching
evidence; conflicts fail closed. Active M7 reliability limits govern response
bytes, requests, artifacts, and free disk. CLI output and review summaries are
sanitized and never contain raw bodies, page IDs, URLs, paths, hashes, titles,
principals, or credentials.
