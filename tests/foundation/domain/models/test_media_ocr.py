from __future__ import annotations

import hashlib

import pytest

from knowledgenexus.foundation.domain.models.media_ocr import (
    OcrLimits,
    OcrRequest,
    OcrRequestStatus,
    OcrResult,
    RasterizedPdfImage,
)
from knowledgenexus.foundation.domain.models.media_processing import MediaSourceLocator, OcrLabelResult


def _locator() -> MediaSourceLocator:
    return MediaSourceLocator(
        parent_page_id="1000", attachment_id="2000", filename="scan.pdf",
        raw_uri="raw://confluence/attachments/2000/" + "a" * 64, image_index=1,
    )


def _request() -> OcrRequest:
    return OcrRequest(
        source_digest="b" * 64, locator=_locator(), selected_image_indices=(1,),
        deadline=None, engine_id="approved-engine", engine_version="v1", limits=OcrLimits(),
        input_bytes=10, raster_bytes=20,
    )


def test_ocr_result_requires_canonical_digest_and_exact_counters() -> None:
    request = _request()
    label = OcrLabelResult(image_index=1, text="hello", confidence=0.9)
    digest = hashlib.sha256(b"1:hello:0.90000000").hexdigest()
    result = OcrResult(request=request, status=OcrRequestStatus.SUCCEEDED, labels=(label,), input_bytes=10,
                       raster_bytes=20, output_bytes=5, images_requested=1, images_processed=1, output_digest=digest)
    assert result.output_digest == digest
    with pytest.raises(ValueError):
        OcrResult(request=request, status=OcrRequestStatus.SUCCEEDED, labels=(label,), input_bytes=10,
                  raster_bytes=20, output_bytes=5, images_requested=1, images_processed=0, output_digest=digest)
    with pytest.raises(ValueError):
        OcrResult(request=request, status=OcrRequestStatus.SUCCEEDED, labels=(label,), input_bytes=10,
                  raster_bytes=20, output_bytes=5, images_requested=1, images_processed=1, output_digest="c" * 64)


def test_ocr_contract_rejects_forged_inputs_and_non_success_output() -> None:
    with pytest.raises((TypeError, ValueError)):
        OcrRequest(source_digest="x", locator=object(), selected_image_indices=(1,), deadline=None,
                   engine_id="engine", engine_version="1")
    request = _request()
    with pytest.raises(ValueError):
        OcrResult(request=request, status=OcrRequestStatus.EMPTY, labels=(), input_bytes=1,
                  raster_bytes=0, output_bytes=0, images_requested=1, images_processed=0)
    with pytest.raises(ValueError):
        RasterizedPdfImage(source_digest="b" * 64, page_number=1, image_index=1, body=b"x", image_digest="a" * 64)


@pytest.mark.parametrize("status,category", [
    (OcrRequestStatus.EMPTY, "empty"),
    (OcrRequestStatus.LOW_CONFIDENCE, "low_confidence"),
    (OcrRequestStatus.CANCELLED, "cancelled"),
    (OcrRequestStatus.LIMIT_EXCEEDED, "limit_exceeded"),
    (OcrRequestStatus.FAILED, "failed"),
])
def test_ocr_status_failure_matrix_is_exact(status: OcrRequestStatus, category: str) -> None:
    request = _request()
    result = OcrResult(request=request, status=status, labels=(), input_bytes=10, raster_bytes=20,
                       output_bytes=0, images_requested=1, images_processed=0,
                       failure_category=category)
    assert result.status is status
    with pytest.raises(ValueError):
        OcrResult(request=request, status=status, labels=(), input_bytes=10, raster_bytes=20,
                  output_bytes=0, images_requested=1, images_processed=0,
                  failure_category="failed" if category != "failed" else "empty")


def test_ocr_request_requires_bound_counters_and_result_rejects_forged_counters() -> None:
    with pytest.raises(ValueError):
        OcrRequest(source_digest="b" * 64, locator=_locator(), selected_image_indices=(1,),
                   deadline=None, engine_id="approved-engine", engine_version="v1")
    request = _request()
    label = OcrLabelResult(image_index=1, text="hello", confidence=0.9)
    digest = hashlib.sha256(b"1:hello:0.90000000").hexdigest()
    with pytest.raises(ValueError):
        OcrResult(request=request, status=OcrRequestStatus.SUCCEEDED, labels=(label,), input_bytes=11,
                  raster_bytes=20, output_bytes=5, images_requested=1, images_processed=1,
                  output_digest=digest)
