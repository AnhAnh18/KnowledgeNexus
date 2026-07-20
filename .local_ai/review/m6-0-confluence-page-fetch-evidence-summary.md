# M6-0 Confluence Page Fetch Live Evidence Summary

> **This is an operator-evidence registration, not a detached code review and not
> a raw evidence archive.** The live run was performed by the operator on the
> connected primary machine. This checkout did not perform it. This record
> synchronizes only the approved sanitized conclusion. No raw production artifact
> is stored here; that exclusion is a deliberate sanitization requirement, not
> missing validation.

## What M6-0 was

An operator live probe confirming that one real Confluence Data Center page can
be fetched with body, restrictions, and attachment metadata, and that the
response shapes match what M6A will build against. It is the page-level analogue
of the M5B-0 inventory probe.

## Confirmed request shapes

Registered from operator observation only; no shape below is inferred here.

- Page: `GET /rest/api/content/{page_id}?expand=body.storage,space,version,ancestors,metadata.labels`
- View restriction: `GET /rest/api/content/{page_id}/restriction/byOperation/view`
- Attachments: `GET /rest/api/content/{page_id}/child/attachment?start={offset}&limit={page_size}`

## Confirmed observations

- The page request returned HTTP 200.
- Every observed method was `GET`.
- Response JSON parsing passed.
- `body.storage` contained XHTML.
- The XHTML initial parse passed.
- The XHTML serialize-then-reparse passed.
- Attachment pagination collected 8 windows and 8 attachments.
- Attachment pagination terminated by following the observed `_links.next`.
- The selected-page view restriction returned 404 and was classified
  **unavailable**.
- 11 ancestor restriction observations returned 404 and were classified
  **unavailable**.
- Unavailable restriction evidence was **not** interpreted as unrestricted.
- The downstream ACL consequence remains deny-safe: `restricted:unresolved`.
- The leak scan passed.
- No credentials appeared in the sanitized evidence.
- Raw production artifacts were intentionally excluded from the sanitized packet.

## Scope registered for M6A

M6A consumes only the **page** request above and preserves its exact raw bytes.
The restriction and attachment shapes are recorded here as confirmed evidence for
later stages; M6A does **not** call the restriction or attachment endpoints.

- M6A endpoint and `expand` shape are **confirmed by approved M6-0**, not inferred
  by the implementer.
- Restriction/ACL interpretation, attachment handling, and XHTML normalization
  belong to later M6 stages (M6B onward), not M6A.

## Provenance and boundary

- Live run: operator, on the connected primary machine.
- This checkout: did not perform the live run and holds no raw artifact.
- This commit: documentation/state only; it registers the approved conclusion so
  `IMPLEMENTATION_STATE.md` and `ROADMAP.md` stop contradicting the operator's
  completed work.
- Absence of raw artifacts is the intended sanitization outcome and must not be
  described as missing validation.

## Not registered

No commit ID, packet path, command, filename, page ID, hostname, page title,
principal, hash, or raw-content detail is recorded, because none was provided to
this checkout and none may be invented.
