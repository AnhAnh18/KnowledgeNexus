from __future__ import annotations

import re

# Confluence Server/Data Center REST representations have used both the raw
# decimal content ID and the legacy ``att``-prefixed content ID for attachments.
# Keep this rule separate from the page-ID rule: an attachment shape must never
# widen a page path or page URL boundary.
_CONFLUENCE_ATTACHMENT_ID = re.compile(r"\A(?:att)?[0-9]+\Z")


def require_confluence_attachment_id(value: object) -> str:
    """Return a canonical REST attachment ID without changing its observed form."""
    if not isinstance(value, str):
        raise TypeError("attachment_id expects a string")
    if _CONFLUENCE_ATTACHMENT_ID.fullmatch(value) is None:
        raise ValueError(
            "attachment_id must be ASCII decimal digits with an optional att prefix"
        )
    return value
