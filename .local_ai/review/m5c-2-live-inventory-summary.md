# M5C-2 Live Confluence Inventory Smoke - Sanitized Summary

## Evidence Boundary

This file registers the operator-reported result of the approved M5C live smoke.
The run occurred on the Confluence-connected primary machine, not on the Codex
development machine. It is a sanitized evidence record, not a raw report archive.

The repository does not contain the live inventory reports, page metadata,
deployment identifiers, request CQL, credentials, or response payloads.

## Result

- Deployment family: Confluence Data Center.
- Access mode: read-only.
- Smoke result: PASS.
- Total inventory items: 9.
- Root items: 1.
- Descendants: 8.
- Included items: 9.
- Excluded-subtree items: 0.
- Maximum relative depth: 2.
- Search windows: 4.
- Page size: 2.
- Maximum search pages: 10.
- JSONL records: 9.
- CSV data rows: 9.

## Artifact Fingerprints

- `pages_inventory.jsonl` SHA-256:
  `40b6c575d43e2c7f006767c7800e927a39e9fed4789265124c8858b6a22092f0`
- `inventory_report.csv` SHA-256:
  `41125e479e63299d9deb25e220f458ef8db059cb13a710c8ac31ae4b35c2a97b`

These hashes identify the operator-verified reports without copying their real
content into the repository.

## Safety Confirmation

- Real reports remained outside the repository.
- No credential material was detected.
- No live output was added to Git.
- No page body, attachment, or ACL data was requested.
- No host, space key, root/page ID, title, path, CQL, PAT, or report content is
  recorded in this summary.

## Known Limitation

Root labels were not requested. Their value is unknown and must not be treated as
confirmed empty or used to choose excluded subtrees.

## Next Gate

M5 is complete. M6 proceeds with one real Confluence page end to end, beginning
with the separately reviewed M6A raw-page preservation gate.
