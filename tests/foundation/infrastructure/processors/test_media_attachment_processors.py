from __future__ import annotations

from pathlib import Path

import pytest
import hashlib

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
from knowledgenexus.foundation.domain.models.media_ocr import OcrLimits, OcrRequestStatus, OcrResult, RasterizedPdfImage
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


def test_pdf_image_only_fallback_is_bound_and_does_not_publish_partial_output() -> None:
    class _Rasterizer:
        def rasterize_pdf_pages(self, *, source_digest: str, body: bytes, page_numbers: tuple[int, ...], limits: object) -> tuple[RasterizedPdfImage, ...]:
            return tuple(RasterizedPdfImage(source_digest=source_digest, page_number=page, image_index=index, body=b"pixels", image_digest=hashlib.sha256(b"pixels").hexdigest()) for index, page in enumerate(page_numbers, 1))

    class _Ocr:
        def recognize(self, *, request: object, images: tuple[RasterizedPdfImage, ...]) -> OcrResult:
            from knowledgenexus.foundation.domain.models.media_processing import OcrLabelResult
            label = OcrLabelResult(image_index=images[0].image_index, text="scan", confidence=0.9)
            digest = hashlib.sha256(f"{label.image_index}:{label.text}:{label.confidence:.8f}".encode()).hexdigest()
            return OcrResult(request=request, status=OcrRequestStatus.SUCCEEDED, labels=(label,), input_bytes=4, raster_bytes=6, output_bytes=4, images_requested=1, images_processed=1, output_digest=digest)

    processor = PdfTextProcessor(
        capability=_PdfCapability(PdfTextExtractionResponse(capability_id="pdf-text-fixture-v1", capability_version="1", pages=(PdfPageTextResult(page_number=1, text="digital"), PdfPageTextResult(page_number=2, text="", image_only=True)))),
        rasterizer=_Rasterizer(), ocr_capability=_Ocr(), ocr_engine_id="approved-engine", ocr_engine_version="v1",
    )
    result = processor.process(envelope=_envelope(), observation=_observation())
    assert result.failure_category is None
    assert result.asset["extracted_text"] == "[pdf_page: 1]\ndigital\n\n[pdf_page: 2] [image: 1] scan"


def test_pdf_fallback_rejects_reordered_raster_pages() -> None:
    class _BadRasterizer:
        def rasterize_pdf_pages(self, *, source_digest: str, body: bytes, page_numbers: tuple[int, ...], limits: object) -> tuple[object, ...]:
            return tuple()

    processor = PdfTextProcessor(
        capability=_PdfCapability(PdfTextExtractionResponse(capability_id="pdf-text-fixture-v1", capability_version="1", pages=(PdfPageTextResult(page_number=1, text="", image_only=True),))),
        rasterizer=_BadRasterizer(), ocr_capability=type("O", (), {"recognize": lambda *args, **kwargs: None})(), ocr_engine_id="approved-engine", ocr_engine_version="v1",
    )
    result = processor.process(envelope=_envelope(), observation=_observation())
    assert result.failure_category is MediaProcessingFailureCategory.CAPABILITY_FAILURE


def test_pdf_fallback_rejects_wrong_source_and_duplicate_image_binding() -> None:
    class _BadRasterizer:
        def rasterize_pdf_pages(self, *, source_digest: str, body: bytes, page_numbers: tuple[int, ...], limits: object) -> tuple[RasterizedPdfImage, ...]:
            wrong = "a" * 64
            return tuple(RasterizedPdfImage(source_digest=wrong, page_number=page, image_index=1, body=b"pixels", image_digest=hashlib.sha256(b"pixels").hexdigest()) for page in page_numbers)
    processor = PdfTextProcessor(
        capability=_PdfCapability(PdfTextExtractionResponse(capability_id="pdf-text-fixture-v1", capability_version="1", pages=(PdfPageTextResult(page_number=1, text="", image_only=True),))),
        rasterizer=_BadRasterizer(), ocr_capability=type("O", (), {"recognize": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call OCR"))})(), ocr_engine_id="approved-engine", ocr_engine_version="v1",
    )
    result = processor.process(envelope=_envelope(), observation=_observation())
    assert result.failure_category is MediaProcessingFailureCategory.CAPABILITY_FAILURE
    assert result.asset["extracted_text"] is None


def test_pdf_fallback_enforces_limits_without_partial_output() -> None:
    class _NeverRaster:
        def rasterize_pdf_pages(self, **kwargs: object) -> tuple[RasterizedPdfImage, ...]:
            raise AssertionError("must reject before rasterization")
    processor = PdfTextProcessor(
        capability=_PdfCapability(PdfTextExtractionResponse(capability_id="pdf-text-fixture-v1", capability_version="1", pages=(PdfPageTextResult(page_number=1, text="", image_only=True),))),
        rasterizer=_NeverRaster(), ocr_capability=type("O", (), {"recognize": lambda *args, **kwargs: None})(), ocr_engine_id="approved-engine", ocr_engine_version="v1", ocr_limits=OcrLimits(max_input_bytes=1),
    )
    result = processor.process(envelope=_envelope(), observation=_observation())
    assert result.failure_category is MediaProcessingFailureCategory.LIMIT_EXCEEDED
    assert result.asset["extracted_text"] is None


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


def test_standalone_ocr_rejects_labels_for_unselected_image() -> None:
    result = ImageOcrProcessor(
        capability=_OcrCapability(
            ImageOcrResponse(
                capability_id="image-ocr-fixture-v1",
                capability_version="1",
                labels=(OcrLabelResult(image_index=2, text="wrong", confidence=0.9),),
            )
        )
    ).process(
        envelope=_envelope(filename="chart.png"),
        observation=_observation(filename="chart.png", mime_type="image/png"),
    )
    assert result.failure_category is MediaProcessingFailureCategory.MALFORMED_RESULT
    assert result.asset["extracted_text"] is None


def test_pdf_fallback_revalidates_forged_ocr_result() -> None:
    class _Rasterizer:
        def rasterize_pdf_pages(self, *, source_digest: str, body: bytes, page_numbers: tuple[int, ...], limits: object) -> tuple[RasterizedPdfImage, ...]:
            return tuple(RasterizedPdfImage(source_digest=source_digest, page_number=page, image_index=1, body=b"pixels", image_digest=hashlib.sha256(b"pixels").hexdigest()) for page in page_numbers)

    class _ForgedOcr:
        def recognize(self, *, request: object, images: tuple[RasterizedPdfImage, ...]) -> object:
            label = OcrLabelResult(image_index=1, text="scan", confidence=0.9)
            digest = hashlib.sha256(f"1:scan:0.90000000".encode()).hexdigest()
            forged = object.__new__(OcrResult)
            object.__setattr__(forged, "request", request)
            object.__setattr__(forged, "status", OcrRequestStatus.SUCCEEDED)
            object.__setattr__(forged, "labels", (label,))
            object.__setattr__(forged, "input_bytes", 4)
            object.__setattr__(forged, "raster_bytes", 6)
            object.__setattr__(forged, "output_bytes", 999)
            object.__setattr__(forged, "images_requested", 1)
            object.__setattr__(forged, "images_processed", 1)
            object.__setattr__(forged, "output_digest", digest)
            object.__setattr__(forged, "failure_category", None)
            return forged

    processor = PdfTextProcessor(
        capability=_PdfCapability(PdfTextExtractionResponse(capability_id="pdf-text-fixture-v1", capability_version="1", pages=(PdfPageTextResult(page_number=1, text="", image_only=True),))),
        rasterizer=_Rasterizer(), ocr_capability=_ForgedOcr(), ocr_engine_id="approved-engine", ocr_engine_version="v1",
    )
    result = processor.process(envelope=_envelope(), observation=_observation())
    assert result.failure_category is MediaProcessingFailureCategory.CAPABILITY_FAILURE
    assert result.asset["extracted_text"] is None


def test_ocr_constructor_rejects_invalid_runtime_inputs() -> None:
    with pytest.raises(Exception):
        ImageOcrProcessor(capability=_OcrCapability(object()), ocr_limits=object())
    with pytest.raises(Exception):
        ImageOcrProcessor(capability=_OcrCapability(object()), clock=object())
    with pytest.raises(Exception):
        ImageOcrProcessor(capability=_OcrCapability(object()), deadline="2026-08-05")


def test_ocr_exact_elapsed_limit_is_inclusive() -> None:
    class _Never:
        def extract_labels(self, *, body: bytes) -> object:
            raise AssertionError("capability must not be called")

    ticks = iter((0.0, 120.0))
    processor = ImageOcrProcessor(capability=_Never(), clock=lambda: next(ticks))
    result = processor.process(envelope=_envelope(filename="chart.png"), observation=_observation(filename="chart.png", mime_type="image/png"))
    assert result.failure_category is MediaProcessingFailureCategory.LIMIT_EXCEEDED


def test_standalone_ocr_rejects_raster_limit_before_capability() -> None:
    class _Never:
        def extract_labels(self, *, body: bytes) -> object:
            raise AssertionError("capability must not be called")
    processor = ImageOcrProcessor(capability=_Never(), ocr_limits=OcrLimits(max_raster_bytes=1))
    result = processor.process(envelope=_envelope(filename="chart.png"), observation=_observation(filename="chart.png", mime_type="image/png"))
    assert result.failure_category is MediaProcessingFailureCategory.LIMIT_EXCEEDED
    assert result.asset["extracted_text"] is None


def test_standalone_ocr_rejects_cancelled_or_expired_request_before_capability() -> None:
    class _Never:
        def extract_labels(self, *, body: bytes) -> object:
            raise AssertionError("capability must not be called")
    processor = ImageOcrProcessor(capability=_Never(), is_cancelled=lambda: True)
    result = processor.process(envelope=_envelope(filename="chart.png"), observation=_observation(filename="chart.png", mime_type="image/png"))
    assert result.failure_category is MediaProcessingFailureCategory.LIMIT_EXCEEDED
    ticks = iter((0.0, 121.0))
    processor = ImageOcrProcessor(capability=_Never(), clock=lambda: next(ticks))
    result = processor.process(envelope=_envelope(filename="chart.png"), observation=_observation(filename="chart.png", mime_type="image/png"))
    assert result.failure_category is MediaProcessingFailureCategory.LIMIT_EXCEEDED


def test_standalone_ocr_rechecks_cancellation_after_capability() -> None:
    state = {"cancelled": False}
    class _Capability:
        def extract_labels(self, *, body: bytes) -> object:
            state["cancelled"] = True
            return ImageOcrResponse(capability_id="image-ocr-fixture-v1", capability_version="1", labels=(OcrLabelResult(image_index=1, text="ok", confidence=0.9),))
    processor = ImageOcrProcessor(capability=_Capability(), is_cancelled=lambda: state["cancelled"])
    result = processor.process(envelope=_envelope(filename="chart.png"), observation=_observation(filename="chart.png", mime_type="image/png"))
    assert result.failure_category is MediaProcessingFailureCategory.LIMIT_EXCEEDED
    assert result.asset["extracted_text"] is None
