from __future__ import annotations

from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
)
from knowledgenexus.foundation.domain.models.media_processing import (
    ImageOcrResponse,
    MediaProcessingFailureCategory,
    OcrLabelResult,
    PdfPageTextResult,
    PdfTextExtractionResponse,
)
from knowledgenexus.foundation.infrastructure.processors.media_attachment_processors import (
    ImageOcrProcessor,
    PdfTextProcessor,
)


def _envelope(body: bytes = b"body", *, filename: str = "file.pdf") -> MediaAttachmentBodyEnvelope:
    return MediaAttachmentBodyEnvelope(
        format_version="1",
        evidence_kind="confluence_attachment_body",
        attachment_id="2000",
        parent_page_id="1000",
        filename=filename,
        source_version="1",
        http_status=200,
        body_encoding="base64",
        body_bytes=body,
    )


def _observation(*, filename: str = "file.pdf", mime_type: str | None = "application/pdf") -> ConfluenceAttachmentObservation:
    return ConfluenceAttachmentObservation(
        attachment_id="2000",
        parent_page_id="1000",
        filename=filename,
        mime_type=mime_type,
        size_bytes=4,
        source_version="1",
        updated_at=None,
        crawled_at="2026-08-05T00:00:00Z",
    )


class _PdfCapability:
    def __init__(self, response: object) -> None:
        self.response = response

    def extract_pdf_text(self, *, body: bytes) -> object:
        return self.response


class _OcrCapability:
    def __init__(self, response: object) -> None:
        self.response = response

    def extract_labels(self, *, body: bytes) -> object:
        return self.response


def test_pdf_processor_is_deterministic_and_preserves_page_markers() -> None:
    processor = PdfTextProcessor(
        capability=_PdfCapability(
            PdfTextExtractionResponse(
                capability_id="pdf-text-fixture-v1",
                capability_version="1",
                pages=(PdfPageTextResult(page_number=1, text="hello"),),
            )
        )
    )
    first = processor.process(envelope=_envelope(), observation=_observation())
    second = processor.process(envelope=_envelope(), observation=_observation())
    assert first == second
    assert first.asset["processing_status"] == "parsed"
    assert first.asset["extracted_text"] == "[pdf_page: 1]\nhello"


def test_pdf_image_only_page_is_explicitly_deferred() -> None:
    processor = PdfTextProcessor(
        capability=_PdfCapability(
            PdfTextExtractionResponse(
                capability_id="pdf-text-fixture-v1",
                capability_version="1",
                pages=(PdfPageTextResult(page_number=1, text="", image_only=True),),
            )
        )
    )
    result = processor.process(envelope=_envelope(), observation=_observation())
    assert result.asset["processing_status"] == "failed"
    assert result.failure_category is MediaProcessingFailureCategory.CAPABILITY_UNAVAILABLE
    assert result.asset["extracted_text"] is None


def test_pdf_forged_response_and_unexpected_exception_fail_closed() -> None:
    forged = object.__new__(PdfTextExtractionResponse)
    result = PdfTextProcessor(capability=_PdfCapability(forged)).process(
        envelope=_envelope(), observation=_observation()
    )
    assert result.failure_category is MediaProcessingFailureCategory.MALFORMED_RESULT

    class _Raising:
        def extract_pdf_text(self, *, body: bytes) -> object:
            raise RuntimeError("secret/path")

    result = PdfTextProcessor(capability=_Raising()).process(
        envelope=_envelope(), observation=_observation()
    )
    assert result.failure_category is MediaProcessingFailureCategory.CAPABILITY_FAILURE


def test_ocr_processor_emits_labels_only_with_confidence() -> None:
    processor = ImageOcrProcessor(
        capability=_OcrCapability(
            ImageOcrResponse(
                capability_id="image-ocr-fixture-v1",
                capability_version="1",
                labels=(OcrLabelResult(image_index=1, text="Title", confidence=0.8),),
            )
        )
    )
    result = processor.process(
        envelope=_envelope(filename="chart.png", body=b"body"),
        observation=_observation(filename="chart.png", mime_type="image/png"),
    )
    assert result.asset["processing_status"] == "ocr"
    assert result.asset["confidence"] == 0.8
    assert result.asset["extracted_text"] == "[image: 1] Title"


def test_ocr_forged_response_is_sanitized() -> None:
    result = ImageOcrProcessor(capability=_OcrCapability(object())).process(
        envelope=_envelope(filename="chart.png"),
        observation=_observation(filename="chart.png", mime_type="image/png"),
    )
    assert result.failure_category is MediaProcessingFailureCategory.MALFORMED_RESULT
