from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)

# Confluence Data Center URL shapes that carry an explicit numeric page id
# without needing a live API lookup:
#   .../pages/viewpage.action?pageId=12345
#   .../spaces/SPACE/pages/12345/Page+Title
_PAGE_ID_PATH_SEGMENT = re.compile(r"/pages/([0-9]+)(?:/|$)")


class ConfluenceUrlParseError(ValueError):
    """Raised when a Confluence URL has no resolvable page id.

    Shapes like tiny links (`/x/AbCdEf`) or space-browse links
    (`/display/SPACE/Page+Title`) require a live Confluence API lookup to
    resolve to a page id, which this offline parser deliberately does not
    perform.
    """


def parse_confluence_page_id(url: str) -> str:
    """Extract a Confluence page id from a URL without any network call."""
    if not isinstance(url, str) or not url:
        raise ConfluenceUrlParseError("url must be a non-empty string")

    parsed = urlparse(url)
    query_page_id = parse_qs(parsed.query).get("pageId")
    if query_page_id:
        candidate = query_page_id[0]
    else:
        match = _PAGE_ID_PATH_SEGMENT.search(parsed.path)
        candidate = match.group(1) if match else None

    if candidate is None:
        raise ConfluenceUrlParseError(
            f"cannot resolve a page id from url without a live lookup: {url}"
        )

    try:
        return require_confluence_page_id(candidate)
    except (TypeError, ValueError) as exc:
        raise ConfluenceUrlParseError(f"invalid page id in url: {url}") from exc
