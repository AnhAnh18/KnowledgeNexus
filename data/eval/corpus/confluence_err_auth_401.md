# Confluence Login Error ERR_AUTH_401

Operators sometimes see **ERR_AUTH_401** when a Confluence Data Center PAT is expired or
the `CONFLUENCE_BASE_URL` host is wrong.

## Checklist

1. Verify `CONFLUENCE_PAT` is valid.
2. Confirm the base URL has no trailing path typos.
3. Retry a single-page fetch via the foundation CLI before bulk inventory.

This document is intentionally keyword-heavy so hybrid / sparse retrieval can be tested
against the exact token `ERR_AUTH_401`.
