from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
)
from knowledgenexus.foundation.domain.models.drawio_xml import (
    DrawioXmlFailureCategory,
    DrawioXmlProcessingError,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
)
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
    text_digest,
)
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.foundation.ports.media_processing_port import (
    ImageOcrPort,
    PdfTextExtractionPort,
)
from knowledgenexus.foundation.infrastructure.processors.drawio_xml_processor import (
    DrawioXmlProcessor,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


_DRAWIO_CAPABILITY = ("stdlib-drawio-v1", "1")
_PDF_CAPABILITY = ("pdf-text-fixture-v1", "1")
_OCR_CAPABILITY = ("image-ocr-fixture-v1", "1")
_MAX_EXTRACTED_BYTES = 8 * 1024 * 1024


def _revalidate_envelope(value: object) -> MediaAttachmentBodyEnvelope:
    if type(value) is not MediaAttachmentBodyEnvelope:
        raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
    try:
        return MediaAttachmentBodyEnvelope(
            format_version=value.format_version,
            evidence_kind=value.evidence_kind,
            attachment_id=value.attachment_id,
            parent_page_id=value.parent_page_id,
            filename=value.filename,
            source_version=value.source_version,
            http_status=value.http_status,
            body_encoding=value.body_encoding,
            body_bytes=value.body_bytes,
        )
    except Exception:
        raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None


def _revalidate_observation(value: object) -> ConfluenceAttachmentObservation:
    if type(value) is not ConfluenceAttachmentObservation:
        raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
    try:
        return ConfluenceAttachmentObservation(
            attachment_id=value.attachment_id,
            parent_page_id=value.parent_page_id,
            filename=value.filename,
            mime_type=value.mime_type,
            size_bytes=value.size_bytes,
            source_version=value.source_version,
            updated_at=value.updated_at,
            crawled_at=value.crawled_at,
        )
    except Exception:
        raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None


def _validate_binding(
    envelope: MediaAttachmentBodyEnvelope,
    observation: ConfluenceAttachmentObservation,
) -> None:
    if (
        envelope.attachment_id != observation.attachment_id
        or envelope.parent_page_id != observation.parent_page_id
        or envelope.filename != observation.filename
        or envelope.source_version != observation.source_version
        or (observation.size_bytes is not None and observation.size_bytes != len(envelope.body_bytes))
    ):
        raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)


def _revalidate_pdf_response(value: object) -> PdfTextExtractionResponse:
    if type(value) is not PdfTextExtractionResponse:
        raise MediaProcessingError(MediaProcessingFailureCategory.MALFORMED_RESULT)
    try:
        return PdfTextExtractionResponse(
            capability_id=value.capability_id,
            capability_version=value.capability_version,
            pages=value.pages,
        )
    except Exception:
        raise MediaProcessingError(MediaProcessingFailureCategory.MALFORMED_RESULT) from None


def _revalidate_ocr_response(value: object) -> ImageOcrResponse:
    if type(value) is not ImageOcrResponse:
        raise MediaProcessingError(MediaProcessingFailureCategory.MALFORMED_RESULT)
    try:
        return ImageOcrResponse(
            capability_id=value.capability_id,
            capability_version=value.capability_version,
            labels=value.labels,
        )
    except Exception:
        raise MediaProcessingError(MediaProcessingFailureCategory.MALFORMED_RESULT) from None


def _asset(
    *,
    envelope: MediaAttachmentBodyEnvelope,
    observation: ConfluenceAttachmentObservation,
    status: str,
    extracted_text: str | None,
    confidence: float | None,
) -> dict[str, object]:
    digest = hashlib.sha256(envelope.body_bytes).hexdigest()
    return {
        "schema_version": "1.0",
        "media_id": DocumentIdGenerator.confluence_attachment_id(observation.attachment_id),
        "parent_document_id": DocumentIdGenerator.confluence_page_id(observation.parent_page_id),
        "source_system": "confluence",
        "filename": observation.filename,
        "mime_type": observation.mime_type,
        "size_bytes": observation.size_bytes,
        "download_status": "downloaded",
        "processing_status": status,
        "relevance": "high",
        "extracted_text": extracted_text,
        "summary": None,
        "confidence": confidence,
        "raw_uri": f"raw://confluence/attachments/{observation.attachment_id}/{digest}",
        "content_hash": digest,
        "source_version": observation.source_version,
        "updated_at": observation.updated_at,
        "crawled_at": observation.crawled_at,
    }


def _locator(
    *,
    observation: ConfluenceAttachmentObservation,
    raw_uri: str,
    pdf_page_number: int | None = None,
    image_index: int | None = None,
) -> MediaSourceLocator:
    return MediaSourceLocator(
        parent_page_id=observation.parent_page_id,
        attachment_id=observation.attachment_id,
        filename=observation.filename,
        raw_uri=raw_uri,
        pdf_page_number=pdf_page_number,
        image_index=image_index,
    )


class PdfTextProcessor:
    def __init__(self, *, capability: PdfTextExtractionPort, schema_validator: object | None = None) -> None:
        try:
            extract = getattr(capability, "extract_pdf_text", None)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
        if not callable(extract):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
            validate = getattr(validator, "validate_record", None)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
        if not callable(validate):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        self._capability = capability
        self._validator = validator

    def process(self, *, envelope: object, observation: object) -> MediaProcessingResult:
        body_envelope = _revalidate_envelope(envelope)
        attachment = _revalidate_observation(observation)
        _validate_binding(body_envelope, attachment)
        try:
            response = self._capability.extract_pdf_text(body=body_envelope.body_bytes)
        except Exception:
            return self._failure(
                body_envelope=body_envelope,
                observation=attachment,
                category=MediaProcessingFailureCategory.CAPABILITY_FAILURE,
                warning="pdf capability failed",
            )
        try:
            response = _revalidate_pdf_response(response)
        except MediaProcessingError as error:
            return self._failure(
                body_envelope=body_envelope,
                observation=attachment,
                category=error.category,
                warning="pdf capability result invalid",
            )
        raw_uri = _asset(
            envelope=body_envelope,
            observation=attachment,
            status="failed",
            extracted_text=None,
            confidence=None,
        )["raw_uri"]
        assert type(raw_uri) is str
        if not response.pages or any(page.image_only for page in response.pages):
            return self._failure(
                body_envelope=body_envelope,
                observation=attachment,
                category=MediaProcessingFailureCategory.CAPABILITY_UNAVAILABLE,
                warning="pdf image-only page deferred",
                response=response,
                raw_uri=raw_uri,
            )
        parts: list[str] = []
        details: list[MediaExtractionDetail] = []
        output_bytes = 0
        for index, page in enumerate(response.pages, start=1):
            page_text = page.text
            if page.table_markdown:
                page_text = f"{page_text}\n{page.table_markdown}" if page_text else page.table_markdown
            marked = f"[pdf_page: {page.page_number}]\n{page_text}".strip()
            projected_bytes = output_bytes + (2 if parts else 0) + len(marked.encode("utf-8"))
            if projected_bytes > _MAX_EXTRACTED_BYTES:
                return self._failure(
                    body_envelope=body_envelope,
                    observation=attachment,
                    category=MediaProcessingFailureCategory.LIMIT_EXCEEDED,
                    warning="pdf output limit exceeded",
                )
            parts.append(marked)
            output_bytes = projected_bytes
            details.append(
                MediaExtractionDetail(
                    ordinal=index,
                    locator=_locator(
                        observation=attachment,
                        raw_uri=raw_uri,
                        pdf_page_number=page.page_number,
                    ),
                    processor_kind=MediaProcessorKind.PDF_TEXT,
                    capability_id=response.capability_id,
                    capability_version=response.capability_version,
                    status="parsed",
                    text_sha256=text_digest(marked),
                )
            )
        text = "\n\n".join(parts)
        if len(text.encode("utf-8")) > _MAX_EXTRACTED_BYTES:
            return self._failure(
                body_envelope=body_envelope,
                observation=attachment,
                category=MediaProcessingFailureCategory.LIMIT_EXCEEDED,
                warning="pdf output limit exceeded",
                response=response,
                raw_uri=raw_uri,
            )
        asset = _asset(
            envelope=body_envelope,
            observation=attachment,
            status="parsed",
            extracted_text=text,
            confidence=None,
        )
        self._validate_asset(asset)
        return MediaProcessingResult(asset=asset, details=tuple(details))

    def _failure(
        self,
        *,
        body_envelope: MediaAttachmentBodyEnvelope,
        observation: ConfluenceAttachmentObservation,
        category: MediaProcessingFailureCategory,
        warning: str,
        response: PdfTextExtractionResponse | None = None,
        raw_uri: str | None = None,
    ) -> MediaProcessingResult:
        if raw_uri is None:
            raw_uri = _asset(
                envelope=body_envelope,
                observation=observation,
                status="failed",
                extracted_text=None,
                confidence=None,
            )["raw_uri"]
        assert type(raw_uri) is str
        pages = response.pages if response is not None and response.pages else (PdfPageTextResult(page_number=1, text=""),)
        details = tuple(
            MediaExtractionDetail(
                ordinal=index,
                locator=_locator(observation=observation, raw_uri=raw_uri, pdf_page_number=page.page_number),
                processor_kind=MediaProcessorKind.PDF_TEXT,
                capability_id=_PDF_CAPABILITY[0],
                capability_version=_PDF_CAPABILITY[1],
                status="failed",
                warning=warning,
            )
            for index, page in enumerate(pages, start=1)
        )
        asset = _asset(
            envelope=body_envelope,
            observation=observation,
            status="failed",
            extracted_text=None,
            confidence=None,
        )
        return MediaProcessingResult(asset=asset, details=details, failure_category=category)

    def _validate_asset(self, asset: dict[str, object]) -> None:
        try:
            self._validator.validate_record("MediaAsset", asset)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.SCHEMA_INVALID) from None


class ImageOcrProcessor:
    def __init__(self, *, capability: ImageOcrPort, schema_validator: object | None = None) -> None:
        try:
            extract = getattr(capability, "extract_labels", None)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
        if not callable(extract):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
            validate = getattr(validator, "validate_record", None)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
        if not callable(validate):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        self._capability = capability
        self._validator = validator

    def process(self, *, envelope: object, observation: object) -> MediaProcessingResult:
        body_envelope = _revalidate_envelope(envelope)
        attachment = _revalidate_observation(observation)
        _validate_binding(body_envelope, attachment)
        try:
            response = self._capability.extract_labels(body=body_envelope.body_bytes)
            response = _revalidate_ocr_response(response)
        except MediaProcessingError as error:
            return self._failure(body_envelope, attachment, error.category, "OCR capability result invalid")
        except Exception:
            return self._failure(
                body_envelope,
                attachment,
                MediaProcessingFailureCategory.CAPABILITY_FAILURE,
                "OCR capability failed",
            )
        if not response.labels:
            return self._failure(
                body_envelope,
                attachment,
                MediaProcessingFailureCategory.PARSE_FAILED,
                "OCR produced no labels",
            )
        raw_uri = _asset(
            envelope=body_envelope,
            observation=attachment,
            status="failed",
            extracted_text=None,
            confidence=None,
        )["raw_uri"]
        assert type(raw_uri) is str
        parts: list[str] = []
        details: list[MediaExtractionDetail] = []
        output_bytes = 0
        for index, label in enumerate(response.labels, start=1):
            marked = f"[image: {label.image_index}] {label.text}"
            projected_bytes = output_bytes + (1 if parts else 0) + len(marked.encode("utf-8"))
            if projected_bytes > _MAX_EXTRACTED_BYTES:
                return self._failure(
                    body_envelope,
                    attachment,
                    MediaProcessingFailureCategory.LIMIT_EXCEEDED,
                    "OCR output limit exceeded",
                )
            parts.append(marked)
            output_bytes = projected_bytes
            details.append(
                MediaExtractionDetail(
                    ordinal=index,
                    locator=_locator(observation=attachment, raw_uri=raw_uri, image_index=label.image_index),
                    processor_kind=MediaProcessorKind.IMAGE_OCR,
                    capability_id=response.capability_id,
                    capability_version=response.capability_version,
                    status="ocr",
                    text_sha256=text_digest(marked),
                )
            )
        confidence = sum(label.confidence for label in response.labels) / len(response.labels)
        if len("\n".join(parts).encode("utf-8")) > _MAX_EXTRACTED_BYTES:
            return self._failure(
                body_envelope,
                attachment,
                MediaProcessingFailureCategory.LIMIT_EXCEEDED,
                "OCR output limit exceeded",
            )
        asset = _asset(
            envelope=body_envelope,
            observation=attachment,
            status="ocr",
            extracted_text="\n".join(parts),
            confidence=confidence,
        )
        try:
            self._validator.validate_record("MediaAsset", asset)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.SCHEMA_INVALID) from None
        return MediaProcessingResult(asset=asset, details=tuple(details))

    @staticmethod
    def _failure(
        body_envelope: MediaAttachmentBodyEnvelope,
        observation: ConfluenceAttachmentObservation,
        category: MediaProcessingFailureCategory,
        warning: str,
    ) -> MediaProcessingResult:
        asset = _asset(
            envelope=body_envelope,
            observation=observation,
            status="failed",
            extracted_text=None,
            confidence=None,
        )
        raw_uri = asset["raw_uri"]
        assert type(raw_uri) is str
        detail = MediaExtractionDetail(
            ordinal=1,
            locator=_locator(observation=observation, raw_uri=raw_uri, image_index=1),
            processor_kind=MediaProcessorKind.IMAGE_OCR,
            capability_id=_OCR_CAPABILITY[0],
            capability_version=_OCR_CAPABILITY[1],
            status="failed",
            warning=warning,
        )
        return MediaProcessingResult(asset=asset, details=(detail,), failure_category=category)


class DrawioProcessor:
    """Project deterministic draw.io XML extraction into the MediaAsset seam."""

    def __init__(self, *, parser: DrawioXmlProcessor | None = None, schema_validator: object | None = None) -> None:
        if parser is not None and type(parser) is not DrawioXmlProcessor:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
            validate = getattr(validator, "validate_record", None)
        except Exception:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
        if not callable(validate):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        self._parser = parser or DrawioXmlProcessor()
        self._validator = validator

    def process(self, *, envelope: object, observation: object) -> MediaProcessingResult:
        body_envelope = _revalidate_envelope(envelope)
        attachment = _revalidate_observation(observation)
        _validate_binding(body_envelope, attachment)
        raw_uri = _asset(
            envelope=body_envelope,
            observation=attachment,
            status="failed",
            extracted_text=None,
            confidence=None,
        )["raw_uri"]
        assert type(raw_uri) is str
        try:
            parsed = self._parser.process(body_envelope.body_bytes)
        except DrawioXmlProcessingError as error:
            category = (
                MediaProcessingFailureCategory.LIMIT_EXCEEDED
                if error.category is DrawioXmlFailureCategory.BOUNDS_EXCEEDED
                else MediaProcessingFailureCategory.PARSE_FAILED
            )
            return self._failure(attachment, body_envelope, raw_uri, category, "draw.io parse failed")
        except Exception:
            return self._failure(
                attachment,
                body_envelope,
                raw_uri,
                MediaProcessingFailureCategory.INTERNAL_FAILURE,
                "draw.io processor failed",
            )
        try:
            text = parsed.extracted_text
            if type(text) is not str or not text:
                raise ValueError("empty draw.io output")
            asset = _asset(
                envelope=body_envelope,
                observation=attachment,
                status="parsed",
                extracted_text=text,
                confidence=None,
            )
            self._validator.validate_record("MediaAsset", asset)
            detail = MediaExtractionDetail(
                ordinal=1,
                locator=_locator(observation=attachment, raw_uri=raw_uri),
                processor_kind=MediaProcessorKind.DRAWIO,
                capability_id=_DRAWIO_CAPABILITY[0],
                capability_version=_DRAWIO_CAPABILITY[1],
                status="parsed",
                text_sha256=text_digest(text),
            )
            return MediaProcessingResult(asset=asset, details=(detail,))
        except MediaProcessingError:
            raise
        except Exception:
            return self._failure(
                attachment,
                body_envelope,
                raw_uri,
                MediaProcessingFailureCategory.SCHEMA_INVALID,
                "draw.io output invalid",
            )

    @staticmethod
    def _failure(
        observation: ConfluenceAttachmentObservation,
        envelope: MediaAttachmentBodyEnvelope,
        raw_uri: str,
        category: MediaProcessingFailureCategory,
        warning: str,
    ) -> MediaProcessingResult:
        asset = _asset(
            envelope=envelope,
            observation=observation,
            status="failed",
            extracted_text=None,
            confidence=None,
        )
        detail = MediaExtractionDetail(
            ordinal=1,
            locator=_locator(observation=observation, raw_uri=raw_uri),
            processor_kind=MediaProcessorKind.DRAWIO,
            capability_id=_DRAWIO_CAPABILITY[0],
            capability_version=_DRAWIO_CAPABILITY[1],
            status="failed",
            warning=warning,
        )
        return MediaProcessingResult(asset=asset, details=(detail,), failure_category=category)


__all__ = ["DrawioProcessor", "ImageOcrProcessor", "PdfTextProcessor"]
