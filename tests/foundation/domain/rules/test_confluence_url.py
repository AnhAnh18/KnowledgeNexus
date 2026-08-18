from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules.confluence_url import (
    ConfluenceUrlParseError,
    parse_confluence_page_id,
)


@pytest.mark.parametrize(
    "url, expected_page_id",
    [
        (
            "https://confluence.example.com/pages/viewpage.action?pageId=12345",
            "12345",
        ),
        (
            "https://confluence.example.com/spaces/SPACE/pages/98765/Page+Title",
            "98765",
        ),
        (
            "https://confluence.example.com/pages/98765",
            "98765",
        ),
    ],
)
def test_parses_supported_url_shapes(url: str, expected_page_id: str) -> None:
    assert parse_confluence_page_id(url) == expected_page_id


@pytest.mark.parametrize(
    "url",
    [
        "https://confluence.example.com/x/AbCdEf",
        "https://confluence.example.com/display/SPACE/Page+Title",
        "https://confluence.example.com/pages/viewpage.action?spaceKey=SPACE",
        "",
    ],
)
def test_rejects_url_shapes_requiring_live_lookup(url: str) -> None:
    with pytest.raises(ConfluenceUrlParseError):
        parse_confluence_page_id(url)


def test_rejects_non_numeric_page_id() -> None:
    with pytest.raises(ConfluenceUrlParseError):
        parse_confluence_page_id(
            "https://confluence.example.com/pages/viewpage.action?pageId=not-a-number"
        )


def test_rejects_non_string_input() -> None:
    with pytest.raises(ConfluenceUrlParseError):
        parse_confluence_page_id(None)  # type: ignore[arg-type]
