from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.media_processing import (
    ImageOcrResponse,
    PdfTextExtractionResponse,
)


class PdfTextExtractionPort(Protocol):
    def extract_pdf_text(self, *, body: bytes) -> PdfTextExtractionResponse: ...


class ImageOcrPort(Protocol):
    def extract_labels(self, *, body: bytes) -> ImageOcrResponse: ...


__all__ = ["ImageOcrPort", "PdfTextExtractionPort"]
