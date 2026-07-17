# M5B-2 Split Review Runbook

These are review-only partitions of the already approved local commit
`a2fe824`. They do not rewrite or alter that commit.

## Base and Order

Use M5B-1 commit `a740b07` as the base and apply the patches in this order:

1. `m5b-2a-http-transport.patch`
2. `m5b-2b-inventory-adapter.patch`

Patch B depends on patch A. Applying A and then B reproduces the five M5B-2
files in `a2fe824` exactly.

## Patch A - HTTP Transport

Files:

- `src/knowledgenexus/foundation/infrastructure/confluence/confluence_http_transport.py`
- `src/knowledgenexus/foundation/infrastructure/confluence/__init__.py`
  (transport exports only)
- `tests/foundation/infrastructure/confluence/test_confluence_http_transport.py`

Review focus:

- HTTPS-only base URL and optional context path.
- Bearer PAT injection without credential disclosure.
- GET-only JSON requests, redirect refusal, timeout, and response-size limit.
- Safe HTTP/network/JSON errors.

Verification:

```powershell
git apply --check .\m5b-2a-http-transport.patch
git apply .\m5b-2a-http-transport.patch
py -3.13 -m pytest tests/foundation/infrastructure/confluence/test_confluence_http_transport.py -q
```

Expected: `39 passed`.

## Patch B - Inventory Adapter

Files:

- `src/knowledgenexus/foundation/infrastructure/confluence/confluence_data_center_inventory_adapter.py`
- `src/knowledgenexus/foundation/infrastructure/confluence/__init__.py`
  (adapter exports only, applied after A)
- `tests/foundation/infrastructure/confluence/test_confluence_data_center_inventory_adapter.py`

Review focus:

- Lazy execution and root-first output.
- Strict root `space.key` postcondition.
- Root-scoped CQL and bounded numeric pagination.
- `totalSize` drift, `_links.next` independence, and request-page budget.
- Integration with the existing M5A scope/report flow.

Verification after patch A:

```powershell
git apply --check .\m5b-2b-inventory-adapter.patch
git apply .\m5b-2b-inventory-adapter.patch
py -3.13 -m pytest tests/foundation/infrastructure/confluence/test_confluence_data_center_inventory_adapter.py -q
py -3.13 -m pytest tests/foundation tests/shared -q
```

Expected:

- Patch B focused: `42 passed`.
- Full Foundation/Shared after A+B: `598 passed`.

## Copy to the Main Machine

Copy these three files together:

- `m5b-2a-http-transport.patch`
- `m5b-2b-inventory-adapter.patch`
- `m5b-2-split-review-runbook.md`

No Confluence credential, deployment identifier, README change, `.local_ai`
evidence packet, or live-network operation is contained in either patch.
