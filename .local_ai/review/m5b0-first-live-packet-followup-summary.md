# M5B-0 First Live Packet Follow-up Summary

## Scope

- Reviewed the sanitized packet at
  `.local_ai/evidence/knowledge-nexus-confluence-packet-20260716-103736`.
- Reviewed only relevant request shapes in the supplied local Tool_TRreport
  source; no credentials or live Confluence access were used.
- Updated only the standalone `.local_ai` probe bundle, tests, runbook, and
  local implementation state. Production Foundation source remains unchanged.

## Evidence conclusion

- Deployment is Confluence Data Center using Bearer PAT and `/rest/api`.
- Root metadata GET succeeded with `expand=version`.
- Pagination uses JSON `/_links/next` with a root-relative URL.
- The first inventory endpoint is rejected for production use: this deployment
  ignored `parent` on `/rest/api/content` and returned pages outside the chosen
  root.
- Tool_TRreport already contains the safer recursive CQL request shape:
  `/rest/api/search` with `space`, `ancestor`, and `type=page`.
- A second sanitized live packet was required to confirm the CQL search result
  envelope and pagination before implementing the deployment adapter; its
  outcome is recorded below.

## Second packet addendum

- Reviewed
  `.local_ai/evidence/knowledge-nexus-confluence-packet-20260716-111725`.
- The packet is structurally safe: five allowed files, valid JSON, no real
  hostname, root ID, space key, PAT marker, or credential material.
- `/rest/api/search` returned nested `content` results and integer `start`,
  `limit`, `size`, and `totalSize` fields.
- With two results at a requested limit of two, `/_links/next` was absent. The
  `json_next` profile therefore terminated prematurely and is rejected for this
  endpoint.
- The working profile now uses the observed numeric `start_limit` envelope and
  metadata-only nested content expansions. A final live confirmation was then
  required for multi-page advancement and expanded metadata shape; its outcome
  is recorded below.

## Final packet conclusion

- Reviewed
  `.local_ai/evidence/knowledge-nexus-confluence-packet-20260716-124055`.
- The packet contains exactly the seven allowed regular files. All JSON parses,
  and targeted scans found no real host, root ID, space key, PAT marker, Bearer
  material, authorization/cookie header, or unexpected artifact.
- Four inventory windows advanced at starts 0, 2, 4, and 6 with limit 2. The
  fourth reached `start + size >= total`; pagination is complete and not
  truncated.
- The eight descendants match the known test tree size. Every sampled result is
  a current page in the requested space and contains the requested root in its
  ordered ancestor chain.
- Confirmed mapping fields are ID, title, space key, ordered ancestor IDs and
  titles, version number, version timestamp, and labels. Parent is derived from
  the last ancestor after trimming the chain to the requested root. Attachment
  count remains `None`.
- Ancestors above the selected root are present and must not leak into the
  relative inventory path. The CQL result excludes the root itself, so the
  adapter must include the separate root response.
- M5B-0 is complete. No further live diagnostic is required before implementing
  and independently reviewing the M5B adapter.

## Follow-up changes

- Added the working non-secret CQL profile at
  `.local_ai/tools/confluence_request_profile.json`.
- Deleted the temporary `confluence_request_profile_1.json`; its unsafe parent
  request and mutable `type` setting were not copied.
- Pagination scope validation now compares decoded immutable query pairs
  without relying on order while preserving duplicate counts.
- Mutable pagination parameters now reject `type`, `status`, `parent`,
  `ancestor`, and `limit` in addition to existing scope keys.
- Added focused regression tests and updated the connected-machine runbook for
  Python 3.13 and the supplied profile.

## Verification status

- Both request-profile JSON files parse successfully.
- Static inspection confirms only `start` is mutable in the working profile.
- No Python runtime is available in the current Codex environment. The updated
  offline tests and profile-only validation therefore remain mandatory on the
  connected machine before the second live diagnostic.
- No live request was attempted from the Codex machine.
