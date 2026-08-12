from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.media_processing import (
    ImageOcrResponse,
    PdfTextExtractionResponse,
)
from knowledgenexus.foundation.domain.models.media_ocr import (
    OcrLimits,
    OcrRequest,
    OcrResult,
    PdfPageRasterizerPort,
    RasterizedPdfImage,
)


class PdfTextExtractionPort(Protocol):
    def extract_pdf_text(self, *, body: bytes) -> PdfTextExtractionResponse: ...


class ImageOcrPort(Protocol):
    def extract_labels(self, *, body: bytes) -> ImageOcrResponse: ...


class OcrCapabilityPort(Protocol):
    """Approved-adapter seam; fixture capabilities remain separate."""

    def recognize(self, *, request: OcrRequest, images: tuple[RasterizedPdfImage, ...]) -> OcrResult: ...


__all__ = ["ImageOcrPort", "PdfTextExtractionPort", "OcrCapabilityPort", "PdfPageRasterizerPort", "OcrLimits", "OcrRequest", "OcrResult"]
