from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Callable

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
from knowledgenexus.foundation.domain.models.media_ocr import OcrLimits, OcrRequest, OcrRequestStatus, OcrResult, RasterizedPdfImage
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.foundation.ports.media_processing_port import (
    ImageOcrPort,
    OcrCapabilityPort,
    PdfPageRasterizerPort,
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
_RFC3339 = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")


def _ocr_cancelled(request: OcrRequest, started: float, clock: object) -> bool:
    try:
        if request.is_cancelled is not None and bool(request.is_cancelled()):
            return True
        if float(clock()) - started >= request.limits.max_seconds:
            return True
        if request.deadline is not None:
            deadline = datetime.fromisoformat(request.deadline.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= deadline:
                return True
    except Exception:
        return True
    return False


def _validate_raster_images(images: object, *, source_digest: str, page_numbers: tuple[int, ...], body_size: int, limits: OcrLimits) -> tuple[RasterizedPdfImage, ...]:
    if type(images) is not tuple or len(images) != len(page_numbers) or len(images) > limits.max_images:
        raise ValueError("rasterizer result count invalid")
    seen: set[int] = set()
    for item, page in zip(images, page_numbers):
        if type(item) is not RasterizedPdfImage or item.source_digest != source_digest or item.page_number != page or item.image_index in seen:
            raise ValueError("rasterizer binding invalid")
        seen.add(item.image_index)
    if sum(len(item.body) for item in images) > limits.max_raster_bytes:
        raise OverflowError("raster byte limit")
    if body_size > limits.max_input_bytes:
        raise OverflowError("input byte limit")
    return images


def _validate_ocr_result(result: object, *, request: OcrRequest, image: RasterizedPdfImage) -> OcrResult:
    if type(result) is not OcrResult:
        raise ValueError("OCR result invalid")
    try:
        # Rebuild nested values so forged same-type dataclasses cannot bypass
        # their own post-init invariants at this capability boundary.
        raw_request = result.request
        rebuilt_request = OcrRequest(
            source_digest=raw_request.source_digest,
            locator=MediaSourceLocator(
                parent_page_id=raw_request.locator.parent_page_id,
                attachment_id=raw_request.locator.attachment_id,
                filename=raw_request.locator.filename,
                raw_uri=raw_request.locator.raw_uri,
                pdf_page_number=raw_request.locator.pdf_page_number,
                image_index=raw_request.locator.image_index,
            ),
            selected_image_indices=raw_request.selected_image_indices,
            deadline=raw_request.deadline,
            engine_id=raw_request.engine_id,
            engine_version=raw_request.engine_version,
            limits=OcrLimits(**{name: getattr(raw_request.limits, name) for name in OcrLimits.__dataclass_fields__}),
            is_cancelled=raw_request.is_cancelled,
            input_bytes=raw_request.input_bytes,
            raster_bytes=raw_request.raster_bytes,
            page_number=raw_request.page_number,
        )
        labels = tuple(
            OcrLabelResult(image_index=label.image_index, text=label.text, confidence=label.confidence)
            for label in result.labels
        )
        rebuilt = OcrResult(
            request=rebuilt_request,
            status=result.status,
            labels=labels,
            input_bytes=result.input_bytes,
            raster_bytes=result.raster_bytes,
            output_bytes=result.output_bytes,
            images_requested=result.images_requested,
            images_processed=result.images_processed,
            output_digest=result.output_digest,
            failure_category=result.failure_category,
        )
    except Exception:
        raise ValueError("OCR result invalid") from None
    if rebuilt.request != request or rebuilt.status is not OcrRequestStatus.SUCCEEDED:
        raise ValueError("OCR result invalid")
    if rebuilt.request.page_number != image.page_number or rebuilt.request.locator.image_index != image.image_index:
        raise ValueError("OCR request binding invalid")
    if rebuilt.images_processed != 1 or tuple(label.image_index for label in rebuilt.labels) != (image.image_index,):
        raise ValueError("OCR labels are not bound")
    if rebuilt.input_bytes != request.input_bytes or rebuilt.raster_bytes != len(image.body):
        raise ValueError("OCR counters invalid")
    return rebuilt


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
    def __init__(self, *, capability: PdfTextExtractionPort, rasterizer: PdfPageRasterizerPort | None = None, ocr_capability: OcrCapabilityPort | None = None, ocr_engine_id: str | None = None, ocr_engine_version: str | None = None, ocr_limits: OcrLimits | None = None, schema_validator: object | None = None, clock: object | None = None) -> None:
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
        if rasterizer is not None and not callable(getattr(rasterizer, "rasterize_pdf_pages", None)):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if ocr_capability is not None and not callable(getattr(ocr_capability, "recognize", None)):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if (rasterizer is None) != (ocr_capability is None):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if ocr_capability is not None and (type(ocr_engine_id) is not str or type(ocr_engine_version) is not str):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if ocr_limits is not None and type(ocr_limits) is not OcrLimits:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if clock is not None and not callable(clock):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        self._rasterizer = rasterizer
        self._ocr_capability = ocr_capability
        self._ocr_engine_id = ocr_engine_id
        self._ocr_engine_version = ocr_engine_version
        self._ocr_limits = ocr_limits or OcrLimits()
        self._clock = time.monotonic if clock is None else clock
        self._validator = validator

    def process(self, *, envelope: object, observation: object) -> MediaProcessingResult:
        body_envelope = _revalidate_envelope(envelope)
        attachment = _revalidate_observation(observation)
        _validate_binding(body_envelope, attachment)
        if len(body_envelope.body_bytes) > self._ocr_limits.max_input_bytes:
            return self._failure(body_envelope=body_envelope, observation=attachment, category=MediaProcessingFailureCategory.LIMIT_EXCEEDED, warning="OCR input limit exceeded")
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
        if not response.pages:
            return self._failure(
                body_envelope=body_envelope,
                observation=attachment,
                category=MediaProcessingFailureCategory.CAPABILITY_UNAVAILABLE,
                warning="pdf image-only page deferred",
                response=response,
                raw_uri=raw_uri,
            )
        image_pages = tuple(page for page in response.pages if page.image_only)
        if image_pages and self._rasterizer is None:
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
            if page.image_only:
                continue
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
                    ordinal=len(details) + 1,
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
        if image_pages:
            try:
                source_digest = hashlib.sha256(body_envelope.body_bytes).hexdigest()
                started = float(self._clock())
                if len(image_pages) > self._ocr_limits.max_images:
                    raise OverflowError
                images = self._rasterizer.rasterize_pdf_pages(
                    source_digest=source_digest,
                    body=body_envelope.body_bytes,
                    page_numbers=tuple(page.page_number for page in image_pages),
                    limits=self._ocr_limits,
                )
                images = _validate_raster_images(images, source_digest=source_digest, page_numbers=tuple(page.page_number for page in image_pages), body_size=len(body_envelope.body_bytes), limits=self._ocr_limits)
                for image in images:
                    locator = _locator(observation=attachment, raw_uri=raw_uri, image_index=image.image_index)
                    if _ocr_cancelled(OcrRequest(source_digest=source_digest, locator=locator, selected_image_indices=(image.image_index,), deadline=None, engine_id=self._ocr_engine_id, engine_version=self._ocr_engine_version, limits=self._ocr_limits, input_bytes=len(body_envelope.body_bytes), raster_bytes=len(image.body), page_number=image.page_number), started, self._clock):
                        raise TimeoutError
                    request = OcrRequest(
                        source_digest=source_digest,
                        locator=locator,
                        selected_image_indices=(image.image_index,),
                        deadline=None,
                        engine_id=self._ocr_engine_id,
                        engine_version=self._ocr_engine_version,
                        limits=self._ocr_limits,
                        input_bytes=len(body_envelope.body_bytes),
                        raster_bytes=len(image.body),
                        page_number=image.page_number,
                    )
                    result = self._ocr_capability.recognize(request=request, images=(image,))
                    result = _validate_ocr_result(result, request=request, image=image)
                    for label in result.labels:
                        if label.confidence < self._ocr_limits.min_confidence or len(label.text.encode("utf-8")) < self._ocr_limits.min_text_bytes:
                            raise LookupError
                        marked = f"[pdf_page: {image.page_number}] [image: {label.image_index}] {label.text}"
                        projected_bytes = output_bytes + (2 if parts else 0) + len(marked.encode("utf-8"))
                        if projected_bytes > min(_MAX_EXTRACTED_BYTES, self._ocr_limits.max_output_bytes):
                            raise OverflowError
                        parts.append(marked)
                        output_bytes = projected_bytes
                        details.append(MediaExtractionDetail(ordinal=len(details) + 1, locator=locator, processor_kind=MediaProcessorKind.IMAGE_OCR, capability_id=self._ocr_engine_id, capability_version=self._ocr_engine_version, status="ocr", text_sha256=text_digest(marked), pdf_page_number=image.page_number))
            except OverflowError:
                return self._failure(body_envelope=body_envelope, observation=attachment, category=MediaProcessingFailureCategory.LIMIT_EXCEEDED, warning="OCR output limit exceeded", response=response, raw_uri=raw_uri)
            except (TimeoutError, LookupError):
                return self._failure(body_envelope=body_envelope, observation=attachment, category=MediaProcessingFailureCategory.LIMIT_EXCEEDED, warning="OCR quality or deadline policy rejected output", response=response, raw_uri=raw_uri)
            except Exception:
                return self._failure(body_envelope=body_envelope, observation=attachment, category=MediaProcessingFailureCategory.CAPABILITY_FAILURE, warning="PDF OCR fallback failed", response=response, raw_uri=raw_uri)
        text = "\n\n".join(parts)
        if len(text.encode("utf-8")) > min(_MAX_EXTRACTED_BYTES, self._ocr_limits.max_output_bytes):
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
    def __init__(self, *, capability: ImageOcrPort, schema_validator: object | None = None, ocr_limits: OcrLimits | None = None, clock: Callable[[], float] | None = None, is_cancelled: Callable[[], bool] | None = None, deadline: str | None = None) -> None:
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
        self._limits = ocr_limits or OcrLimits()
        if clock is not None and not callable(clock):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if is_cancelled is not None and not callable(is_cancelled):
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        if deadline is not None:
            if type(deadline) is not str:
                raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
            if _RFC3339.fullmatch(deadline) is None:
                raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
            try:
                datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            except Exception:
                raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT) from None
        if ocr_limits is not None and type(ocr_limits) is not OcrLimits:
            raise MediaProcessingError(MediaProcessingFailureCategory.INVALID_INPUT)
        self._clock = clock or time.monotonic
        self._is_cancelled = is_cancelled
        self._deadline = deadline

    def process(self, *, envelope: object, observation: object) -> MediaProcessingResult:
        body_envelope = _revalidate_envelope(envelope)
        attachment = _revalidate_observation(observation)
        _validate_binding(body_envelope, attachment)
        started = float(self._clock())
        if len(body_envelope.body_bytes) > self._limits.max_input_bytes:
            return self._failure(body_envelope, attachment, MediaProcessingFailureCategory.LIMIT_EXCEEDED, "OCR input limit exceeded")
        if len(body_envelope.body_bytes) > self._limits.max_raster_bytes:
            return self._failure(body_envelope, attachment, MediaProcessingFailureCategory.LIMIT_EXCEEDED, "OCR raster limit exceeded")
        if self._cancelled(started):
            return self._failure(body_envelope, attachment, MediaProcessingFailureCategory.LIMIT_EXCEEDED, "OCR request cancelled or expired")
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
        if self._cancelled(started):
            return self._failure(body_envelope, attachment, MediaProcessingFailureCategory.LIMIT_EXCEEDED, "OCR request cancelled or expired")
        if not response.labels:
            return self._failure(
                body_envelope,
                attachment,
                MediaProcessingFailureCategory.PARSE_FAILED,
                "OCR produced no labels",
            )
        if any(label.image_index != 1 for label in response.labels):
            return self._failure(body_envelope, attachment, MediaProcessingFailureCategory.MALFORMED_RESULT, "OCR labels are not bound to the selected image")
        if len(response.labels) > self._limits.max_images or any(label.confidence < self._limits.min_confidence or len(label.text.encode("utf-8")) < self._limits.min_text_bytes for label in response.labels):
            return self._failure(body_envelope, attachment, MediaProcessingFailureCategory.LIMIT_EXCEEDED, "OCR quality policy rejected output")
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
            if projected_bytes > min(_MAX_EXTRACTED_BYTES, self._limits.max_output_bytes):
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
        if len("\n".join(parts).encode("utf-8")) > min(_MAX_EXTRACTED_BYTES, self._limits.max_output_bytes):
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

    def _cancelled(self, started: float) -> bool:
        try:
            if self._is_cancelled is not None and bool(self._is_cancelled()):
                return True
            if float(self._clock()) - started >= self._limits.max_seconds:
                return True
            if self._deadline is not None:
                deadline = datetime.fromisoformat(self._deadline.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) >= deadline:
                    return True
        except Exception:
            return True
        return False

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
