from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from knowledgenexus.foundation.domain.models.media_processing import (
    MediaSourceLocator,
    OcrLabelResult,
)


_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_ENGINE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,127}\Z")
_RFC3339 = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")


class OcrRequestStatus(StrEnum):
    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    LOW_CONFIDENCE = "low_confidence"
    CANCELLED = "cancelled"
    LIMIT_EXCEEDED = "limit_exceeded"
    FAILED = "failed"


@dataclass(frozen=True, repr=False)
class OcrLimits:
    max_input_bytes: int = 32 * 1024 * 1024
    max_raster_bytes: int = 64 * 1024 * 1024
    max_output_bytes: int = 8 * 1024 * 1024
    max_images: int = 100
    max_seconds: float = 120.0
    min_confidence: float = 0.0
    min_text_bytes: int = 1

    def __post_init__(self) -> None:
        for name in ("max_input_bytes", "max_raster_bytes", "max_output_bytes", "max_images", "min_text_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} is invalid")
        if type(self.max_seconds) not in (int, float) or not math.isfinite(float(self.max_seconds)) or self.max_seconds <= 0:
            raise ValueError("max_seconds is invalid")
        if type(self.min_confidence) not in (int, float) or not math.isfinite(float(self.min_confidence)) or not 0.0 <= float(self.min_confidence) <= 1.0:
            raise ValueError("min_confidence is invalid")
        object.__setattr__(self, "max_seconds", float(self.max_seconds))
        object.__setattr__(self, "min_confidence", float(self.min_confidence))


@dataclass(frozen=True, repr=False)
class OcrRequest:
    source_digest: str
    locator: MediaSourceLocator
    selected_image_indices: tuple[int, ...]
    deadline: str | None
    engine_id: str
    engine_version: str
    limits: OcrLimits = OcrLimits()
    is_cancelled: Callable[[], bool] | None = None
    input_bytes: int | None = None
    raster_bytes: int | None = None
    page_number: int | None = None

    def __post_init__(self) -> None:
        if type(self.source_digest) is not str or _SHA256.fullmatch(self.source_digest) is None:
            raise ValueError("source_digest is invalid")
        if type(self.locator) is not MediaSourceLocator:
            raise TypeError("locator is invalid")
        if type(self.selected_image_indices) is not tuple or not self.selected_image_indices:
            raise ValueError("selected_image_indices are invalid")
        previous = 0
        for value in self.selected_image_indices:
            if type(value) is not int or value <= previous:
                raise ValueError("selected_image_indices are invalid")
            previous = value
        if self.locator.image_index is not None and self.selected_image_indices != (self.locator.image_index,):
            raise ValueError("selected_image_indices do not match locator")
        if self.deadline is not None and (type(self.deadline) is not str or _RFC3339.fullmatch(self.deadline) is None):
            raise ValueError("deadline is invalid")
        for name in ("engine_id", "engine_version"):
            value = getattr(self, name)
            if type(value) is not str or not value or len(value) > 128 or (name == "engine_id" and _ENGINE.fullmatch(value) is None):
                raise ValueError(f"{name} is invalid")
        if type(self.limits) is not OcrLimits:
            raise TypeError("limits are invalid")
        if self.is_cancelled is not None and not callable(self.is_cancelled):
            raise TypeError("is_cancelled is invalid")
        for name in ("input_bytes", "raster_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} is invalid")
        if self.page_number is not None and (type(self.page_number) is not int or self.page_number <= 0):
            raise ValueError("page_number is invalid")


@dataclass(frozen=True, repr=False)
class OcrResult:
    request: OcrRequest
    status: OcrRequestStatus
    labels: tuple[OcrLabelResult, ...]
    input_bytes: int
    raster_bytes: int
    output_bytes: int
    images_requested: int
    images_processed: int
    output_digest: str | None = None
    failure_category: str | None = None

    def __post_init__(self) -> None:
        if type(self.request) is not OcrRequest:
            raise TypeError("request is invalid")
        if not isinstance(self.status, OcrRequestStatus):
            raise TypeError("status is invalid")
        if type(self.labels) is not tuple or any(type(label) is not OcrLabelResult for label in self.labels):
            raise TypeError("labels are invalid")
        for name in ("input_bytes", "raster_bytes", "output_bytes", "images_requested", "images_processed"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} is invalid")
        if self.request.input_bytes is None or self.request.raster_bytes is None:
            raise ValueError("request counters are required")
        if self.input_bytes != self.request.input_bytes or self.raster_bytes != self.request.raster_bytes:
            raise ValueError("request counters are not canonical")
        if self.images_requested != len(self.request.selected_image_indices) or self.images_processed > self.images_requested:
            raise ValueError("image counters are invalid")
        indices = tuple(label.image_index for label in self.labels)
        if any(label.image_index not in self.request.selected_image_indices for label in self.labels) or indices != tuple(sorted(set(indices))):
            raise ValueError("label locator is invalid")
        if self.status is OcrRequestStatus.SUCCEEDED and self.images_processed != len(indices):
            raise ValueError("images_processed is not canonical")
        if self.input_bytes > self.request.limits.max_input_bytes or self.raster_bytes > self.request.limits.max_raster_bytes or self.output_bytes > self.request.limits.max_output_bytes:
            raise ValueError("resource counters exceed limits")
        if self.status is OcrRequestStatus.SUCCEEDED:
            if not self.labels or self.images_processed != self.images_requested or self.failure_category is not None:
                raise ValueError("successful result is invalid")
            if any(label.confidence < self.request.limits.min_confidence for label in self.labels):
                raise ValueError("successful result confidence is invalid")
            if any(len(label.text.encode("utf-8")) < self.request.limits.min_text_bytes for label in self.labels):
                raise ValueError("successful result text quality is invalid")
            expected = hashlib.sha256("\n".join(f"{x.image_index}:{x.text}:{x.confidence:.8f}" for x in self.labels).encode()).hexdigest()
            if self.output_digest != expected:
                raise ValueError("output_digest is invalid")
            expected_output_bytes = len("\n".join(x.text for x in self.labels).encode("utf-8"))
            if self.output_bytes != expected_output_bytes:
                raise ValueError("output_bytes is not canonical")
        else:
            if self.labels or self.output_digest is not None or self.images_processed != 0 or self.output_bytes != 0:
                raise ValueError("non-success result carries output")
            if self.failure_category is None:
                raise ValueError("failure_category is missing")
        if self.failure_category is not None and (type(self.failure_category) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", self.failure_category)):
            raise ValueError("failure_category is invalid")
        allowed_categories = {
            OcrRequestStatus.EMPTY: "empty",
            OcrRequestStatus.LOW_CONFIDENCE: "low_confidence",
            OcrRequestStatus.CANCELLED: "cancelled",
            OcrRequestStatus.LIMIT_EXCEEDED: "limit_exceeded",
            OcrRequestStatus.FAILED: "failed",
        }
        if self.status is OcrRequestStatus.SUCCEEDED:
            if self.failure_category is not None:
                raise ValueError("successful result failure category is invalid")
        elif self.failure_category != allowed_categories[self.status]:
            raise ValueError("failure category is incompatible with status")


@dataclass(frozen=True, repr=False)
class RasterizedPdfImage:
    source_digest: str
    page_number: int
    image_index: int
    body: bytes
    image_digest: str

    def __post_init__(self) -> None:
        if type(self.source_digest) is not str or _SHA256.fullmatch(self.source_digest) is None:
            raise ValueError("source_digest is invalid")
        if type(self.page_number) is not int or self.page_number <= 0 or type(self.image_index) is not int or self.image_index <= 0:
            raise ValueError("image locator is invalid")
        if type(self.body) is not bytes or not self.body:
            raise ValueError("body is invalid")
        if type(self.image_digest) is not str or self.image_digest != hashlib.sha256(self.body).hexdigest():
            raise ValueError("image_digest is invalid")


class PdfPageRasterizerPort:
    """Capability boundary; implementations must be approved separately."""

    def rasterize_pdf_pages(self, *, source_digest: str, body: bytes, page_numbers: tuple[int, ...], limits: OcrLimits) -> tuple[RasterizedPdfImage, ...]:
        raise NotImplementedError


__all__ = ["OcrLimits", "OcrRequest", "OcrRequestStatus", "OcrResult", "PdfPageRasterizerPort", "RasterizedPdfImage"]
