from __future__ import annotations

import hashlib
from pathlib import PurePath

from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
)
from knowledgenexus.foundation.domain.models.media_processing import (
    MediaExtractionDetail,
    MediaProcessingError,
    MediaProcessingFailureCategory,
    MediaProcessingResult,
    MediaProcessorKind,
    MediaSourceLocator,
)
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


_DRAWIO_MIMES = frozenset({
    "application/vnd.jgraph.mxfile",
    "application/x-drawio",
    "application/drawio",
})
_PDF_MIMES = frozenset({"application/pdf"})
_IMAGE_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
})
_DRAWIO_SUFFIXES = (".drawio", ".drawio.xml")
_PDF_SUFFIXES = (".pdf",)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")


def _fail(category: MediaProcessingFailureCategory) -> None:
    raise MediaProcessingError(category) from None


def _revalidate_envelope(value: object) -> MediaAttachmentBodyEnvelope:
    if type(value) is not MediaAttachmentBodyEnvelope:
        _fail(MediaProcessingFailureCategory.INVALID_INPUT)
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
        _fail(MediaProcessingFailureCategory.INVALID_INPUT)


def _revalidate_observation(value: object) -> ConfluenceAttachmentObservation:
    if type(value) is not ConfluenceAttachmentObservation:
        _fail(MediaProcessingFailureCategory.INVALID_INPUT)
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
        _fail(MediaProcessingFailureCategory.INVALID_INPUT)


class ProcessConfluenceMediaAttachment:
    """Route one materialized attachment through an offline processor."""

    def __init__(
        self,
        *,
        drawio_processor: object | None = None,
        pdf_processor: object | None = None,
        ocr_processor: object | None = None,
        schema_validator: object | None = None,
    ) -> None:
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
            validate = getattr(validator, "validate_record", None)
        except Exception:
            _fail(MediaProcessingFailureCategory.INVALID_INPUT)
        if not callable(validate):
            _fail(MediaProcessingFailureCategory.INVALID_INPUT)
        self._drawio = drawio_processor
        self._pdf = pdf_processor
        self._ocr = ocr_processor
        for processor in (self._drawio, self._pdf, self._ocr):
            if processor is not None:
                try:
                    process = getattr(processor, "process", None)
                except Exception:
                    _fail(MediaProcessingFailureCategory.INVALID_INPUT)
                if not callable(process):
                    _fail(MediaProcessingFailureCategory.INVALID_INPUT)
        self._validator = validator

    def execute(self, *, envelope: object, observation: object) -> MediaProcessingResult:
        body = _revalidate_envelope(envelope)
        attachment = _revalidate_observation(observation)
        if (
            body.attachment_id != attachment.attachment_id
            or body.parent_page_id != attachment.parent_page_id
            or body.filename != attachment.filename
            or body.source_version != attachment.source_version
            or (attachment.size_bytes is not None and attachment.size_bytes != len(body.body_bytes))
        ):
            _fail(MediaProcessingFailureCategory.INVALID_INPUT)
        kind = self._route(attachment.filename, attachment.mime_type)
        if kind is None:
            _fail(MediaProcessingFailureCategory.UNSUPPORTED_MEDIA)
        processor = {
            MediaProcessorKind.DRAWIO: self._drawio,
            MediaProcessorKind.PDF_TEXT: self._pdf,
            MediaProcessorKind.IMAGE_OCR: self._ocr,
        }[kind]
        if processor is None:
            return self._failed_result(
                body,
                attachment,
                kind,
                MediaProcessingFailureCategory.CAPABILITY_UNAVAILABLE,
            )
        try:
            result = processor.process(envelope=body, observation=attachment)
        except MediaProcessingError:
            raise
        except Exception:
            _fail(MediaProcessingFailureCategory.INTERNAL_FAILURE)
        if type(result) is not MediaProcessingResult:
            _fail(MediaProcessingFailureCategory.MALFORMED_RESULT)
        try:
            result = MediaProcessingResult(
                asset=result.asset,
                details=result.details,
                failure_category=result.failure_category,
            )
        except Exception:
            _fail(MediaProcessingFailureCategory.MALFORMED_RESULT)
        asset = result.asset
        expected_media_id = DocumentIdGenerator.confluence_attachment_id(attachment.attachment_id)
        expected_parent_id = DocumentIdGenerator.confluence_page_id(attachment.parent_page_id)
        expected_content_hash = hashlib.sha256(body.body_bytes).hexdigest()
        expected_raw_uri = (
            f"raw://confluence/attachments/{attachment.attachment_id}/{expected_content_hash}"
        )
        if (
            asset["media_id"] != expected_media_id
            or asset["parent_document_id"] != expected_parent_id
            or asset["filename"] != attachment.filename
            or asset["mime_type"] != attachment.mime_type
            or asset["size_bytes"] != attachment.size_bytes
            or asset["content_hash"] != expected_content_hash
            or asset["raw_uri"] != expected_raw_uri
        ):
            _fail(MediaProcessingFailureCategory.MALFORMED_RESULT)
        if any(detail.processor_kind is not kind for detail in result.details):
            _fail(MediaProcessingFailureCategory.MALFORMED_RESULT)
        try:
            self._validator.validate_record("MediaAsset", asset)
        except Exception:
            _fail(MediaProcessingFailureCategory.SCHEMA_INVALID)
        return result

    @staticmethod
    def _route(filename: str, mime_type: str | None) -> MediaProcessorKind | None:
        suffix = PurePath(filename.lower()).suffix
        lowered = filename.lower()
        if mime_type in _DRAWIO_MIMES or lowered.endswith(_DRAWIO_SUFFIXES):
            return MediaProcessorKind.DRAWIO
        if mime_type in _PDF_MIMES or suffix in _PDF_SUFFIXES:
            return MediaProcessorKind.PDF_TEXT
        if mime_type in _IMAGE_MIMES or suffix in _IMAGE_SUFFIXES:
            return MediaProcessorKind.IMAGE_OCR
        return None

    def _failed_result(
        self,
        envelope: MediaAttachmentBodyEnvelope,
        observation: ConfluenceAttachmentObservation,
        kind: MediaProcessorKind,
        category: MediaProcessingFailureCategory,
    ) -> MediaProcessingResult:
        digest = hashlib.sha256(envelope.body_bytes).hexdigest()
        raw_uri = f"raw://confluence/attachments/{observation.attachment_id}/{digest}"
        asset = {
            "schema_version": "1.0",
            "media_id": DocumentIdGenerator.confluence_attachment_id(observation.attachment_id),
            "parent_document_id": DocumentIdGenerator.confluence_page_id(observation.parent_page_id),
            "source_system": "confluence",
            "filename": observation.filename,
            "mime_type": observation.mime_type,
            "size_bytes": observation.size_bytes,
            "download_status": "downloaded",
            "processing_status": "failed",
            "relevance": "high",
            "extracted_text": None,
            "summary": None,
            "confidence": None,
            "raw_uri": raw_uri,
            "content_hash": digest,
            "source_version": observation.source_version,
            "updated_at": observation.updated_at,
            "crawled_at": observation.crawled_at,
        }
        locator = MediaSourceLocator(
            parent_page_id=observation.parent_page_id,
            attachment_id=observation.attachment_id,
            filename=observation.filename,
            raw_uri=raw_uri,
            pdf_page_number=1 if kind is MediaProcessorKind.PDF_TEXT else None,
            image_index=1 if kind is MediaProcessorKind.IMAGE_OCR else None,
        )
        detail = MediaExtractionDetail(
            ordinal=1,
            locator=locator,
            processor_kind=kind,
            capability_id={
                MediaProcessorKind.DRAWIO: "stdlib-drawio-v1",
                MediaProcessorKind.PDF_TEXT: "pdf-text-fixture-v1",
                MediaProcessorKind.IMAGE_OCR: "image-ocr-fixture-v1",
            }[kind],
            capability_version="1",
            status="failed",
            warning="processor capability unavailable",
        )
        try:
            self._validator.validate_record("MediaAsset", asset)
            return MediaProcessingResult(
                asset=asset,
                details=(detail,),
                failure_category=category,
            )
        except Exception:
            _fail(MediaProcessingFailureCategory.SCHEMA_INVALID)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


__all__ = ["ProcessConfluenceMediaAttachment"]
