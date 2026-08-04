from __future__ import annotations

import base64
import json

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEvidenceError,
    ConfluenceRawPageEnvelope,
    M7_RAW_PAGE_REQUEST_PROFILE_VERSION,
)

RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")
OTHER_RUN_ID = CrawlRunId("87654321-4321-4234-9234-cba987654321")


def _envelope(*, body: bytes = b"body", source_version: str | None = "v1") -> ConfluenceRawPageEnvelope:
    return ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID,
        page_id="1000",
        source_version=source_version,
        http_status=200,
        body_bytes=body,
    )


def test_capture_serializes_canonical_exact_bytes() -> None:
    envelope = _envelope(body=b"\x00\xff\n")
    serialized = envelope.to_bytes()

    assert ConfluenceRawPageEnvelope.from_bytes(serialized) == envelope
    assert serialized.endswith(b"}")
    assert b"\n" not in serialized
    assert repr(envelope) == "ConfluenceRawPageEnvelope()"


def test_empty_body_and_null_source_version_round_trip() -> None:
    envelope = _envelope(body=b"", source_version=None)

    assert ConfluenceRawPageEnvelope.from_bytes(envelope.to_bytes()) == envelope


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(body_byte_count=99),
        lambda payload: payload.update(body_sha256="0" * 64),
        lambda payload: payload.update(run_id=str(OTHER_RUN_ID)),
        lambda payload: payload.update(generation_id=str(OTHER_RUN_ID)),
        lambda payload: payload.update(page_id="../escape"),
        lambda payload: payload.update(http_status=True),
        lambda payload: payload.update(source_version=""),
    ],
)
def test_invalid_envelope_fields_fail_closed(mutate) -> None:
    payload = json.loads(_envelope().to_bytes())
    mutate(payload)

    with pytest.raises(ConfluenceRawPageEvidenceError):
        ConfluenceRawPageEnvelope.from_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )


def test_duplicate_and_noncanonical_json_are_rejected() -> None:
    serialized = _envelope().to_bytes()
    duplicate = serialized[:-1] + b',"page_id":"1000"}'
    noncanonical = json.dumps(
        json.loads(serialized), sort_keys=False, separators=(", ", ": ")
    ).encode()

    with pytest.raises(ConfluenceRawPageEvidenceError):
        ConfluenceRawPageEnvelope.from_bytes(duplicate)
    with pytest.raises(ConfluenceRawPageEvidenceError):
        ConfluenceRawPageEnvelope.from_bytes(noncanonical)


def test_fixed_request_profile_is_required() -> None:
    with pytest.raises(ValueError):
        ConfluenceRawPageEnvelope.capture(
            run_id=RUN_ID,
            page_id="1000",
            source_version=None,
            http_status=200,
            body_bytes=b"body",
            request_profile_version="other",
        )


def test_body_encoding_is_strict_base64() -> None:
    payload = json.loads(_envelope().to_bytes())
    payload["body_base64"] = base64.b64encode(b"body").decode()[:-1]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(ConfluenceRawPageEvidenceError):
        ConfluenceRawPageEnvelope.from_bytes(serialized)


def test_profile_constant_is_stable() -> None:
    assert M7_RAW_PAGE_REQUEST_PROFILE_VERSION == "m7-confluence-request-profile-v1"
