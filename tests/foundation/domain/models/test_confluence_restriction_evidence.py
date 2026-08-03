from __future__ import annotations

import json

import pytest

from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
    ConfluenceRestrictionEvidenceError,
    M7_RESTRICTION_REQUEST_PROFILE_VERSION,
)


SELECTED = "1000"
TARGET = "1001"


def _envelope(*, status: int = 200, body: bytes = b"raw\x00\xff"):
    return ConfluenceRestrictionEvidenceEnvelope.capture(
        request_profile_version=M7_RESTRICTION_REQUEST_PROFILE_VERSION,
        selected_page_id=SELECTED,
        target_page_id=TARGET,
        http_status=status,
        body_bytes=body,
    )


def _payload(*, body: bytes = b"raw\x00\xff") -> dict[str, object]:
    return json.loads(_envelope(body=body).to_bytes())


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_status_200_arbitrary_bytes_round_trip_exactly() -> None:
    envelope = _envelope(status=200, body=b"not restriction json\x00\xff")

    serialized = envelope.to_bytes()
    restored = ConfluenceRestrictionEvidenceEnvelope.from_bytes(serialized)

    assert restored == envelope
    assert restored.body_bytes == b"not restriction json\x00\xff"


def test_status_404_empty_body_round_trip_exactly() -> None:
    envelope = _envelope(status=404, body=b"")

    restored = ConfluenceRestrictionEvidenceEnvelope.from_bytes(envelope.to_bytes())

    assert restored.http_status == 404
    assert restored.body_bytes == b""
    assert json.loads(envelope.to_bytes())["body_base64"] == ""


@pytest.mark.parametrize("status", [401, 403])
def test_other_completed_statuses_are_accepted(status: int) -> None:
    assert ConfluenceRestrictionEvidenceEnvelope.from_bytes(
        _envelope(status=status).to_bytes()
    ).http_status == status


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, 300, 599])
def test_retryable_and_other_statuses_are_rejected(status: int) -> None:
    with pytest.raises(ConfluenceRestrictionEvidenceError) as exc_info:
        _envelope(status=status)

    assert str(exc_info.value) == "raw_artifact_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_profile_version", "other-profile"),
        ("selected_page_id", ""),
        ("selected_page_id", "1/../2"),
        ("target_page_id", True),
        ("http_status", True),
        ("body_bytes", bytearray(b"bytes")),
    ],
)
def test_capture_rejects_invalid_identity_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "request_profile_version": M7_RESTRICTION_REQUEST_PROFILE_VERSION,
        "selected_page_id": SELECTED,
        "target_page_id": TARGET,
        "http_status": 200,
        "body_bytes": b"body",
    }
    values[field] = value

    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.capture(**values)  # type: ignore[arg-type]


def test_serialization_is_canonical_and_repeatable() -> None:
    envelope = _envelope()

    first = envelope.to_bytes()
    second = envelope.to_bytes()

    assert first == second
    assert first == _canonical(_payload())
    assert b"\n" not in first


@pytest.mark.parametrize(
    "encoded",
    [
        " ",
        "A",
        "YQ=",
        "Y!@=",
        "-w==",
        "_w==",
    ],
)
def test_parser_rejects_non_strict_base64(encoded: str) -> None:
    payload = _payload(body=b"x")
    payload["body_base64"] = encoded
    serialized = _canonical(payload)

    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(serialized)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("body_byte_count", 99),
        ("body_byte_count", True),
        ("body_byte_count", 1.0),
        ("body_sha256", "0" * 64),
        ("body_sha256", "A" * 64),
        ("body_sha256", "not-a-hash"),
    ],
)
def test_parser_rejects_count_and_hash_mismatch(field: str, value: object) -> None:
    payload = _payload(body=b"x")
    payload[field] = value

    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(_canonical(payload))


@pytest.mark.parametrize(
    "serialized",
    [
        b"[]",
        b"null",
        b"{\"http_status\":NaN}",
        b"\x80",
        b"\xef\xbb\xbf{}",
    ],
)
def test_parser_rejects_non_object_or_bom(serialized: bytes) -> None:
    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(serialized)


def test_parser_rejects_duplicate_field() -> None:
    serialized = (
        b'{"body_base64":"","body_byte_count":0,"body_encoding":"base64",'
        b'"body_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",'
        b'"evidence_kind":"confluence_restriction_observation","format_version":"1",'
        b'"http_status":200,"http_status":200,"request_kind":"view_restriction",'
        b'"request_profile_version":"m7-confluence-request-profile-v1",'
        b'"selected_page_id":"1000","target_page_id":"1001"}'
    )

    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(serialized)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.pop("target_page_id"),
        lambda payload: payload.__setitem__("extra", True),
        lambda payload: payload.__setitem__("http_status", 2e2),
        lambda payload: payload.__setitem__("body_byte_count", 0.0),
        lambda payload: payload.__setitem__("format_version", "2"),
    ],
)
def test_parser_rejects_field_shape_and_fixed_value_changes(mutator) -> None:
    payload = _payload(body=b"")
    mutator(payload)

    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(_canonical(payload))


@pytest.mark.parametrize(
    "serialized",
    [
        lambda: json.dumps(_payload(), indent=2).encode("utf-8"),
        lambda: _canonical(_payload()).replace(b'"view_restriction"', b'"view\\u005frestriction"'),
        lambda: _canonical(_payload()) + b"\n",
    ],
)
def test_parser_rejects_noncanonical_bytes_without_rewrite(serialized) -> None:
    original = serialized()

    with pytest.raises(ConfluenceRestrictionEvidenceError):
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(original)

    assert original == serialized()


def test_error_and_repr_are_sanitized() -> None:
    envelope = _envelope(body=b"secret-body")
    rendered = repr(envelope)
    assert rendered == "ConfluenceRestrictionEvidenceEnvelope()"
    assert "secret-body" not in rendered
    assert "1000" not in rendered

    with pytest.raises(ConfluenceRestrictionEvidenceError) as exc_info:
        invalid = envelope.to_bytes().replace(
            b'"body_byte_count":11', b'"body_byte_count":12'
        )
        ConfluenceRestrictionEvidenceEnvelope.from_bytes(
            invalid
        )
    assert str(exc_info.value) == "raw_artifact_invalid"
    assert "secret-body" not in repr(exc_info.value)
