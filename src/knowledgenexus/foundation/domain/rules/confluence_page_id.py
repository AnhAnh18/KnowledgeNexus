from __future__ import annotations

import re

# Confluence Data Center content IDs are ASCII decimal. This is the single
# source of truth for the shape, shared by the raw page store (path safety) and
# the page adapter (URL safety). It is intentionally strict, not a loose
# sanitizer.
_CONFLUENCE_PAGE_ID = re.compile(r"\A[0-9]+\Z")


def require_confluence_page_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("page_id expects a string")
    if _CONFLUENCE_PAGE_ID.fullmatch(value) is None:
        raise ValueError("page_id must contain ASCII decimal digits only")
    return value
