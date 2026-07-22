from __future__ import annotations

import pytest

from knowledgenexus.foundation.application.use_cases.parse_wiki_document_structure import (
    parse_wiki_document_structure,
)
from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageNormalizationResult,
)
from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiProseBlock,
)
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    CATEGORY_INVALID_PAGE_TITLE,
    WikiStructureParseError,
)


def _result(*, title: object, body: str, include_title: bool = True) -> ConfluencePageNormalizationResult:
    canonical_document: dict[str, object] = {
        "schema_version": "1.0",
        "document_id": "doc:confluence:page:1",
    }
    if include_title:
        canonical_document["title"] = title
    return ConfluencePageNormalizationResult(
        normalized_body_text=body,
        canonical_document=canonical_document,
        counters={},
        warnings=(),
    )


def test_title_is_read_from_canonical_document() -> None:
    result = _result(title="Design Note", body="intro\n\n## Locking\n\nbody")
    document = parse_wiki_document_structure(result)
    assert document.page_title == "Design Note"
    assert document.sections[0].heading_path == ("Design Note",)
    assert document.sections[1].heading_path == ("Design Note", "Locking")


def test_empty_body_yields_zero_sections() -> None:
    document = parse_wiki_document_structure(_result(title="Page", body=""))
    assert document.page_title == "Page"
    assert document.sections == ()


def test_prose_only_body_is_single_preamble_block() -> None:
    document = parse_wiki_document_structure(_result(title="Page", body="only prose"))
    assert len(document.sections) == 1
    assert isinstance(document.sections[0].blocks[0], WikiProseBlock)


@pytest.mark.parametrize("title", [None, "", "   "])
def test_missing_or_empty_title_fails_closed(title: object) -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse_wiki_document_structure(_result(title=title, body="body"))
    assert excinfo.value.category == CATEGORY_INVALID_PAGE_TITLE


def test_absent_title_key_fails_closed() -> None:
    result = _result(title=None, body="body", include_title=False)
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse_wiki_document_structure(result)
    assert excinfo.value.category == CATEGORY_INVALID_PAGE_TITLE


def test_non_string_title_fails_closed() -> None:
    with pytest.raises(WikiStructureParseError) as excinfo:
        parse_wiki_document_structure(_result(title=123, body="body"))
    assert excinfo.value.category == CATEGORY_INVALID_PAGE_TITLE
