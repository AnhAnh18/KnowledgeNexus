from __future__ import annotations

import hashlib

import pytest

from knowledgenexus.foundation.domain.models.media_processing import (
    ImageOcrResponse,
    MediaExtractionDetail,
    MediaProcessingError,
    MediaProcessingFailureCategory,
    MediaProcessingResult,
    MediaProcessorKind,
    MediaSourceLocator,
    OcrLabelResult,
    PdfPageTextResult,
    PdfTextExtractionResponse,
)


def _locator(*, page: int | None = None, image: int | None = None) -> MediaSourceLocator:
    return MediaSourceLocator(
        parent_page_id="1000",
        attachment_id="2000",
        filename="diagram.drawio",
        raw_uri=(
            "raw://confluence/attachments/2000/"
            + "a" * 64
        ),
        pdf_page_number=page,
        image_index=image,
    )


def _asset(*, status: str = "parsed", text: str | None = "A -> B", confidence: float | None = None) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "media_id": "confluence:attachment:2000",
        "parent_document_id": "confluence:page:1000",
        "source_system": "confluence",
        "filename": "diagram.drawio",
        "mime_type": "application/xml",
        "size_bytes": 4,
        "download_status": "downloaded",
        "processing_status": status,
        "relevance": "high",
        "extracted_text": text,
        "summary": None,
        "confidence": confidence,
        "raw_uri": "raw://confluence/attachments/2000/" + "a" * 64,
        "content_hash": "a" * 64,
        "source_version": "1",
        "updated_at": None,
        "crawled_at": "2026-08-05T00:00:00Z",
    }


def test_pdf_response_rebuilds_and_requires_ordered_pages() -> None:
    response = PdfTextExtractionResponse(
        capability_id="pdf-text-fixture-v1",
        capability_version="1",
        pages=(PdfPageTextResult(page_number=1, text="first"),),
    )
    assert response.pages[0].text == "first"
    with pytest.raises(ValueError):
        PdfTextExtractionResponse(
            capability_id="pdf-text-fixture-v1",
            capability_version="1",
            pages=(
                PdfPageTextResult(page_number=2, text="two"),
                PdfPageTextResult(page_number=1, text="one"),
            ),
        )


def test_pdf_image_only_page_cannot_carry_text() -> None:
    with pytest.raises(ValueError):
        PdfPageTextResult(page_number=1, text="hidden", image_only=True)
    with pytest.raises(ValueError):
        PdfPageTextResult(page_number=1_000_001, text="page")


def test_ocr_response_rejects_nonfinite_or_forged_labels() -> None:
    with pytest.raises(ValueError):
        OcrLabelResult(image_index=1, text="label", confidence=1.1)
    with pytest.raises(ValueError):
        OcrLabelResult(image_index=1_000_001, text="label", confidence=0.5)
    forged = object.__new__(OcrLabelResult)
    with pytest.raises(ValueError):
        ImageOcrResponse(
            capability_id="image-ocr-fixture-v1",
            capability_version="1",
            labels=(forged,),
        )


def test_locator_rejects_cross_kind_and_bad_identity() -> None:
    with pytest.raises(ValueError):
        _locator(page=1, image=1)
    with pytest.raises(ValueError):
        MediaSourceLocator(
            parent_page_id="1000",
            attachment_id="2000",
            filename="x",
            raw_uri="file:///secret",
        )


def test_processing_result_enforces_status_and_detail_consistency() -> None:
    text = "A -> B"
    detail = MediaExtractionDetail(
        ordinal=1,
        locator=_locator(),
        processor_kind=MediaProcessorKind.DRAWIO,
        capability_id="stdlib-drawio-v1",
        capability_version="1",
        status="parsed",
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    result = MediaProcessingResult(asset=_asset(text=text), details=(detail,))
    assert result.asset["processing_status"] == "parsed"
    failed_detail = MediaExtractionDetail(
        ordinal=1,
        locator=_locator(),
        processor_kind=MediaProcessorKind.DRAWIO,
        capability_id="stdlib-drawio-v1",
        capability_version="1",
        status="failed",
        warning="parse failed",
    )
    with pytest.raises(ValueError):
        MediaProcessingResult(
            asset=_asset(status="failed", text=None),
            details=(failed_detail,),
        )
    with pytest.raises(TypeError):
        MediaProcessingError("secret")  # type: ignore[arg-type]
