from __future__ import annotations

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageNormalizationResult,
)
from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiDocumentStructure,
)
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    WikiStructureParser,
)


def parse_wiki_document_structure(
    result: ConfluencePageNormalizationResult,
) -> WikiDocumentStructure:
    """Adapt one approved M6C normalization result into a wiki structure.

    The page title is read from the M6C canonical document; no duplicate title
    field is added to the M6C boundary. A missing, null, non-string, or
    empty-after-trimming title fails closed inside the parser as
    ``invalid_page_title``. The already-canonical body is passed through
    unchanged.
    """
    canonical_document = result.canonical_document
    page_title = (
        canonical_document.get("title")
        if isinstance(canonical_document, dict)
        else None
    )
    return WikiStructureParser.parse(
        page_title=page_title,
        normalized_body_text=result.normalized_body_text,
    )
