from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from knowledgenexus.foundation.domain.rules.confluence_attachment_id import (
    require_confluence_attachment_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_PAGE_ID = re.compile(r"^confluence:page:[0-9]+$")
_MEDIA_ID = re.compile(r"^confluence:attachment:(?:att)?[0-9]+$")
_MIME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+/[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SOURCE_VERSION = re.compile(r"^[^\x00-\x1f\x7f-\x9f]{1,256}$")
_ENGINE_CAPABILITY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_RFC3339 = re.compile(
    r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?:[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.[0-9]+)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_MAX_TEXT_BYTES = 4 * 1024 * 1024
_MAX_WARNING_BYTES = 512
_MAX_PAGE_NUMBER = 1_000_000
_MAX_IMAGE_INDEX = 1_000_000
_MAX_CAPABILITY_RECORDS = 10_000
_ASSET_FIELDS = frozenset(
    {
        "schema_version",
        "media_id",
        "parent_document_id",
        "source_system",
        "filename",
        "mime_type",
        "size_bytes",
        "download_status",
        "processing_status",
        "relevance",
        "extracted_text",
        "summary",
        "confidence",
        "raw_uri",
        "content_hash",
        "source_version",
        "updated_at",
        "crawled_at",
    }
)


def _filename(value: object) -> str:
    if type(value) is not str:
        raise TypeError("filename is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 512
        or "/" in normalized
        or "\\" in normalized
        or any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in normalized)
    ):
        raise ValueError("filename is invalid")
    return normalized


def _text(value: object, field: str, *, allow_empty: bool = True) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} is invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (not allow_empty and not normalized) or len(normalized.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{field} is invalid")
    if any(ord(character) < 0x20 and character not in "\n\t" for character in normalized):
        raise ValueError(f"{field} is invalid")
    return normalized


def _id(value: object, *, page: bool) -> str:
    if type(value) is not str:
        raise TypeError("identity is invalid")
    try:
        return require_confluence_page_id(value) if page else require_confluence_attachment_id(value)
    except (TypeError, ValueError):
        raise ValueError("identity is invalid") from None


class MediaProcessorKind(StrEnum):
    DRAWIO = "drawio"
    PDF_TEXT = "pdf_text"
    IMAGE_OCR = "image_ocr"


class MediaProcessingFailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_MEDIA = "unsupported_media"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CAPABILITY_FAILURE = "capability_failure"
    MALFORMED_RESULT = "malformed_result"
    LIMIT_EXCEEDED = "limit_exceeded"
    PARSE_FAILED = "parse_failed"
    SCHEMA_INVALID = "schema_invalid"
    INTERNAL_FAILURE = "internal_failure"


class MediaProcessingError(Exception):
    """Sanitized failure from the offline media-processing boundary."""

    def __init__(self, category: MediaProcessingFailureCategory) -> None:
        if not isinstance(category, MediaProcessingFailureCategory):
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)

    def __repr__(self) -> str:
        try:
            category = self.category.value
        except Exception:
            return f"{type(self).__name__}()"
        return f"{type(self).__name__}(category={category!r})"


@dataclass(frozen=True, repr=False)
class MediaSourceLocator:
    parent_page_id: str
    attachment_id: str
    filename: str
    raw_uri: str
    pdf_page_number: int | None = None
    image_index: int | None = None

    def __post_init__(self) -> None:
        parent_page_id = _id(self.parent_page_id, page=True)
        attachment_id = _id(self.attachment_id, page=False)
        filename = _filename(self.filename)
        expected_prefix = f"raw://confluence/attachments/{attachment_id}/"
        if (
            type(self.raw_uri) is not str
            or not self.raw_uri.startswith(expected_prefix)
            or _SHA256.fullmatch(self.raw_uri[len(expected_prefix) :]) is None
        ):
            raise ValueError("raw_uri is invalid")
        if self.pdf_page_number is not None:
            if type(self.pdf_page_number) is not int or self.pdf_page_number <= 0:
                raise ValueError("pdf_page_number is invalid")
        if self.image_index is not None:
            if type(self.image_index) is not int or self.image_index <= 0:
                raise ValueError("image_index is invalid")
        if self.pdf_page_number is not None and self.image_index is not None:
            raise ValueError("locator kind is invalid")
        object.__setattr__(self, "parent_page_id", parent_page_id)
        object.__setattr__(self, "attachment_id", attachment_id)
        object.__setattr__(self, "filename", filename)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


_CAPABILITIES = {
    MediaProcessorKind.PDF_TEXT: ("pdf-text-fixture-v1", "1"),
    MediaProcessorKind.IMAGE_OCR: ("image-ocr-fixture-v1", "1"),
}


def _capability(kind: MediaProcessorKind, name: object, version: object) -> tuple[str, str]:
    if not isinstance(kind, MediaProcessorKind) or type(name) is not str or type(version) is not str:
        raise TypeError("capability identity is invalid")
    expected = _CAPABILITIES.get(kind)
    if expected != (name, version):
        raise ValueError("capability identity is invalid")
    return expected


@dataclass(frozen=True, repr=False)
class PdfPageTextResult:
    page_number: int
    text: str
    table_markdown: str | None = None
    image_only: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.page_number) is not int
            or not 0 < self.page_number <= _MAX_PAGE_NUMBER
        ):
            raise ValueError("page_number is invalid")
        text = _text(self.text, "text")
        if self.table_markdown is not None:
            table = _text(self.table_markdown, "table_markdown")
        else:
            table = None
        if type(self.image_only) is not bool:
            raise TypeError("image_only is invalid")
        if self.image_only and (text or table):
            raise ValueError("image-only page contains text")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "table_markdown", table)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class PdfTextExtractionResponse:
    capability_id: str
    capability_version: str
    pages: tuple[PdfPageTextResult, ...]

    def __post_init__(self) -> None:
        _capability(MediaProcessorKind.PDF_TEXT, self.capability_id, self.capability_version)
        if type(self.pages) is not tuple:
            raise TypeError("pages are invalid")
        if len(self.pages) > _MAX_CAPABILITY_RECORDS:
            raise ValueError("pages are invalid")
        rebuilt: list[PdfPageTextResult] = []
        previous = 0
        for page in self.pages:
            if type(page) is not PdfPageTextResult:
                raise TypeError("pages are invalid")
            try:
                rebuilt_page = PdfPageTextResult(
                    page_number=page.page_number,
                    text=page.text,
                    table_markdown=page.table_markdown,
                    image_only=page.image_only,
                )
            except Exception:
                raise ValueError("pages are invalid") from None
            if rebuilt_page.page_number <= previous:
                raise ValueError("page order is invalid")
            previous = rebuilt_page.page_number
            rebuilt.append(rebuilt_page)
        object.__setattr__(self, "pages", tuple(rebuilt))

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class OcrLabelResult:
    image_index: int
    text: str
    confidence: float

    def __post_init__(self) -> None:
        if (
            type(self.image_index) is not int
            or not 0 < self.image_index <= _MAX_IMAGE_INDEX
        ):
            raise ValueError("image_index is invalid")
        text = _text(self.text, "text", allow_empty=False)
        if type(self.confidence) is not float or not math.isfinite(self.confidence):
            raise TypeError("confidence is invalid")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence is invalid")
        object.__setattr__(self, "text", text)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class ImageOcrResponse:
    capability_id: str
    capability_version: str
    labels: tuple[OcrLabelResult, ...]

    def __post_init__(self) -> None:
        _capability(MediaProcessorKind.IMAGE_OCR, self.capability_id, self.capability_version)
        if type(self.labels) is not tuple:
            raise TypeError("labels are invalid")
        if len(self.labels) > _MAX_CAPABILITY_RECORDS:
            raise ValueError("labels are invalid")
        rebuilt: list[OcrLabelResult] = []
        previous = 0
        for label in self.labels:
            if type(label) is not OcrLabelResult:
                raise TypeError("labels are invalid")
            try:
                rebuilt_label = OcrLabelResult(
                    image_index=label.image_index,
                    text=label.text,
                    confidence=label.confidence,
                )
            except Exception:
                raise ValueError("labels are invalid") from None
            if rebuilt_label.image_index <= previous:
                raise ValueError("image order is invalid")
            previous = rebuilt_label.image_index
            rebuilt.append(rebuilt_label)
        object.__setattr__(self, "labels", tuple(rebuilt))

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True, repr=False)
class MediaExtractionDetail:
    ordinal: int
    locator: MediaSourceLocator
    processor_kind: MediaProcessorKind
    capability_id: str
    capability_version: str
    status: str
    text_sha256: str | None = None
    warning: str | None = None
    pdf_page_number: int | None = None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise ValueError("ordinal is invalid")
        if type(self.locator) is not MediaSourceLocator:
            raise TypeError("locator is invalid")
        if self.pdf_page_number is not None and (type(self.pdf_page_number) is not int or self.pdf_page_number <= 0):
            raise ValueError("pdf_page_number is invalid")
        try:
            locator = MediaSourceLocator(
                parent_page_id=self.locator.parent_page_id,
                attachment_id=self.locator.attachment_id,
                filename=self.locator.filename,
                raw_uri=self.locator.raw_uri,
                pdf_page_number=self.locator.pdf_page_number,
                image_index=self.locator.image_index,
            )
        except Exception:
            raise ValueError("locator is invalid") from None
        if not isinstance(self.processor_kind, MediaProcessorKind):
            raise TypeError("processor_kind is invalid")
        if self.processor_kind is MediaProcessorKind.IMAGE_OCR:
            if type(self.capability_id) is not str or not _ENGINE_CAPABILITY.fullmatch(self.capability_id) or type(self.capability_version) is not str or not self.capability_version:
                raise ValueError("capability identity is invalid")
        elif self.processor_kind in _CAPABILITIES:
            _capability(self.processor_kind, self.capability_id, self.capability_version)
        elif (self.capability_id, self.capability_version) != ("stdlib-drawio-v1", "1"):
            raise ValueError("capability identity is invalid")
        if type(self.status) is not str or self.status not in {"parsed", "ocr", "failed"}:
            raise ValueError("status is invalid")
        if self.text_sha256 is not None and (
            type(self.text_sha256) is not str or _SHA256.fullmatch(self.text_sha256) is None
        ):
            raise ValueError("text_sha256 is invalid")
        if self.processor_kind is MediaProcessorKind.DRAWIO:
            if self.locator.pdf_page_number is not None or self.locator.image_index is not None:
                raise ValueError("draw.io locator is invalid")
            if self.status not in {"parsed", "failed"}:
                raise ValueError("draw.io status is invalid")
        elif self.processor_kind is MediaProcessorKind.PDF_TEXT:
            if self.locator.pdf_page_number is None or self.locator.image_index is not None:
                raise ValueError("PDF locator is invalid")
            if self.status not in {"parsed", "ocr", "failed"}:
                raise ValueError("PDF status is invalid")
        elif self.processor_kind is MediaProcessorKind.IMAGE_OCR:
            if self.locator.image_index is None or self.locator.pdf_page_number is not None:
                raise ValueError("OCR locator is invalid")
            if self.status not in {"ocr", "failed"}:
                raise ValueError("OCR status is invalid")
        if self.status in {"parsed", "ocr"} and self.text_sha256 is None:
            raise ValueError("successful detail digest is missing")
        if self.status == "failed" and self.text_sha256 is not None:
            raise ValueError("failed detail carries digest")
        if self.status == "failed" and self.warning is None:
            raise ValueError("failed detail warning is missing")
        if self.status in {"parsed", "ocr"} and self.warning is not None:
            raise ValueError("successful detail carries warning")
        if self.warning is not None:
            warning = _text(self.warning, "warning", allow_empty=False)
            if len(warning.encode("utf-8")) > _MAX_WARNING_BYTES:
                raise ValueError("warning is invalid")
            object.__setattr__(self, "warning", warning)
        object.__setattr__(self, "locator", locator)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class _MediaAssetValidator:
    @staticmethod
    def validate(asset: object, *, failure_category: MediaProcessingFailureCategory | None) -> dict[str, object]:
        if type(asset) is not dict:
            raise ValueError("asset fields are invalid")
        if any(type(key) is not str for key in asset):
            raise TypeError("asset keys are invalid")
        if set(asset) != _ASSET_FIELDS:
            raise ValueError("asset fields are invalid")
        copied = dict(asset)
        if type(copied["schema_version"]) is not str or copied["schema_version"] != "1.0":
            raise ValueError("asset identity is invalid")
        if type(copied["source_system"]) is not str or copied["source_system"] != "confluence":
            raise ValueError("asset identity is invalid")
        if type(copied["media_id"]) is not str or _MEDIA_ID.fullmatch(copied["media_id"]) is None:
            raise ValueError("asset media_id is invalid")
        if type(copied["parent_document_id"]) is not str or _PAGE_ID.fullmatch(copied["parent_document_id"]) is None:
            raise ValueError("asset parent_document_id is invalid")
        _filename(copied["filename"])
        mime_type = copied["mime_type"]
        if mime_type is not None and (
            type(mime_type) is not str or _MIME.fullmatch(mime_type.strip().lower()) is None
        ):
            raise ValueError("asset mime_type is invalid")
        size_bytes = copied["size_bytes"]
        if size_bytes is not None and (type(size_bytes) is not int or size_bytes < 0):
            raise ValueError("asset size_bytes is invalid")
        if copied["download_status"] != "downloaded":
            raise ValueError("asset download_status is invalid")
        status = copied["processing_status"]
        if type(status) is not str or status not in {"parsed", "ocr", "failed"}:
            raise ValueError("asset processing_status is invalid")
        raw_uri = copied["raw_uri"]
        if type(raw_uri) is not str or copied["content_hash"] is None:
            raise ValueError("asset evidence is invalid")
        if type(copied["content_hash"]) is not str or _SHA256.fullmatch(copied["content_hash"]) is None:
            raise ValueError("asset content_hash is invalid")
        attachment_id = copied["media_id"].rsplit(":", 1)[-1]
        expected_uri = f"raw://confluence/attachments/{attachment_id}/{copied['content_hash']}"
        if raw_uri != expected_uri:
            raise ValueError("asset raw_uri is invalid")
        if copied["source_version"] is not None and (
            type(copied["source_version"]) is not str
            or _SOURCE_VERSION.fullmatch(copied["source_version"]) is None
        ):
            raise ValueError("asset source_version is invalid")
        for field in ("updated_at", "crawled_at"):
            timestamp = copied[field]
            if timestamp is not None and (type(timestamp) is not str or _RFC3339.fullmatch(timestamp) is None):
                raise ValueError(f"asset {field} is invalid")
        if copied["crawled_at"] is None:
            raise ValueError("asset crawled_at is invalid")
        for field in ("extracted_text", "summary"):
            value = copied[field]
            if value is not None:
                _text(value, f"asset {field}")
        if copied["relevance"] not in {"high", "medium", "low", "unknown"}:
            raise ValueError("asset relevance is invalid")
        if status == "failed":
            if any(copied[field] is not None for field in ("extracted_text", "summary", "confidence")):
                raise ValueError("failed asset carries derived text")
            if failure_category is None:
                raise ValueError("failed asset category is missing")
        else:
            if type(copied["extracted_text"]) is not str or not copied["extracted_text"]:
                raise ValueError("processed asset text is invalid")
            if failure_category is not None:
                raise ValueError("successful asset carries failure category")
            if status == "ocr":
                if type(copied["confidence"]) is not float or not math.isfinite(copied["confidence"]):
                    raise ValueError("OCR confidence is invalid")
                if not 0.0 <= copied["confidence"] <= 1.0:
                    raise ValueError("OCR confidence is invalid")
            elif copied["confidence"] is not None:
                raise ValueError("parsed asset confidence is invalid")
        return copied


@dataclass(frozen=True, repr=False)
class MediaProcessingResult:
    asset: dict[str, object]
    details: tuple[MediaExtractionDetail, ...]
    failure_category: MediaProcessingFailureCategory | None = None

    def __post_init__(self) -> None:
        if self.failure_category is not None and not isinstance(
            self.failure_category, MediaProcessingFailureCategory
        ):
            raise TypeError("failure_category is invalid")
        asset = _MediaAssetValidator.validate(self.asset, failure_category=self.failure_category)
        if type(self.details) is not tuple or not self.details:
            raise ValueError("details are invalid")
        rebuilt: list[MediaExtractionDetail] = []
        seen_locators: set[tuple[object, ...]] = set()
        for expected, detail in enumerate(self.details, start=1):
            if type(detail) is not MediaExtractionDetail:
                raise TypeError("details are invalid")
            try:
                copied = MediaExtractionDetail(
                    ordinal=detail.ordinal,
                    locator=detail.locator,
                    processor_kind=detail.processor_kind,
                    capability_id=detail.capability_id,
                    capability_version=detail.capability_version,
                    status=detail.status,
                    text_sha256=detail.text_sha256,
                    warning=detail.warning,
                )
            except Exception:
                raise ValueError("details are invalid") from None
            if copied.ordinal != expected:
                raise ValueError("detail order is invalid")
            locator_key = (
                copied.locator.parent_page_id,
                copied.locator.attachment_id,
                copied.locator.raw_uri,
                copied.locator.pdf_page_number,
                copied.locator.image_index,
            )
            if locator_key in seen_locators:
                raise ValueError("duplicate detail locator")
            seen_locators.add(locator_key)
            rebuilt.append(copied)
        status = asset["processing_status"]
        if status == "failed":
            if any(detail.status != "failed" for detail in rebuilt):
                raise ValueError("detail status mismatch")
        elif any(detail.status not in {"parsed", "ocr"} for detail in rebuilt):
            raise ValueError("detail status mismatch")
        for detail in rebuilt:
            locator = detail.locator
            if (
                f"confluence:page:{locator.parent_page_id.removeprefix('confluence:page:')}"
                != asset["parent_document_id"]
                or f"confluence:attachment:{locator.attachment_id}"
                != asset["media_id"]
                or locator.raw_uri != asset["raw_uri"]
            ):
                raise ValueError("detail asset binding mismatch")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "details", tuple(rebuilt))

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def text_digest(value: str) -> str:
    if type(value) is not str:
        raise TypeError("text is invalid")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ImageOcrResponse",
    "MediaExtractionDetail",
    "MediaProcessingError",
    "MediaProcessingFailureCategory",
    "MediaProcessingResult",
    "MediaProcessorKind",
    "MediaSourceLocator",
    "OcrLabelResult",
    "PdfPageTextResult",
    "PdfTextExtractionResponse",
    "text_digest",
]
