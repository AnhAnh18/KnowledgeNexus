from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_restriction_orphan_inspection import (
    ConfluenceRawRestrictionOrphanInspectionDecision as Decision,
    ConfluenceRawRestrictionOrphanInspectionError,
    ConfluenceRawRestrictionOrphanInspectionFailureCategory as FailureCategory,
    ConfluenceRawRestrictionOrphanInspectionRequest,
)
from knowledgenexus.foundation.domain.models.confluence_restriction_evidence import (
    ConfluenceRestrictionEvidenceEnvelope,
    M7_RESTRICTION_REQUEST_PROFILE_VERSION,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawRestrictionEvidenceStore,
    ConfluenceRawRestrictionOrphanInspector,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    confluence_raw_restriction_orphan_inspector as inspector_module,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
    _MAX_STABLE_READ_BYTES,
)

RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")
OTHER_RUN_ID = CrawlRunId("87654321-4321-4234-9234-cba987654321")


def _envelope(
    *,
    selected: str = "1000",
    target: str = "1001",
    status: int = 200,
    body: bytes = b"body",
) -> ConfluenceRestrictionEvidenceEnvelope:
    return ConfluenceRestrictionEvidenceEnvelope.capture(
        request_profile_version=M7_RESTRICTION_REQUEST_PROFILE_VERSION,
        selected_page_id=selected,
        target_page_id=target,
        http_status=status,
        body_bytes=body,
    )


def _request(
    *,
    run_id: CrawlRunId = RUN_ID,
    selected: str = "1000",
    target: str = "1001",
) -> ConfluenceRawRestrictionOrphanInspectionRequest:
    return ConfluenceRawRestrictionOrphanInspectionRequest.capture(
        run_id=run_id,
        selected_page_id=selected,
        target_page_id=target,
    )


def _target(tmp_path: Path, *, run_id: CrawlRunId = RUN_ID) -> Path:
    return (
        tmp_path
        / "confluence"
        / "generations"
        / str(run_id)
        / "restrictions"
        / "1000"
        / "1001.json"
    )


def _publish(tmp_path: Path, envelope: ConfluenceRestrictionEvidenceEnvelope) -> Path:
    return ConfluenceRawRestrictionEvidenceStore(raw_root=tmp_path).publish_restriction(
        run_id=RUN_ID,
        envelope=envelope,
    ).path


def test_invalid_root_and_request_use_typed_sanitized_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfluenceRawRestrictionOrphanInspectionError) as root_error:
        ConfluenceRawRestrictionOrphanInspector(raw_root=tmp_path / "missing")
    assert root_error.value.category is FailureCategory.RAW_ROOT_INVALID

    inspector = ConfluenceRawRestrictionOrphanInspector(raw_root=tmp_path)
    with pytest.raises(ConfluenceRawRestrictionOrphanInspectionError) as request_error:
        inspector.inspect_restriction(request=object())  # type: ignore[arg-type]
    assert request_error.value.category is FailureCategory.INVALID_REQUEST


def test_missing_parent_and_target_are_read_only(tmp_path: Path) -> None:
    inspector = ConfluenceRawRestrictionOrphanInspector(raw_root=tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = inspector.inspect_restriction(request=_request())

    assert result.decision is Decision.MISSING
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before

    _target(tmp_path).parent.mkdir(parents=True)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = inspector.inspect_restriction(request=_request())
    assert result.decision is Decision.MISSING
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize("status", [200, 401, 403, 404])
@pytest.mark.parametrize("body", [b"", b"arbitrary\x00\xff body"])
def test_completed_restriction_evidence_is_replayable(
    tmp_path: Path, status: int, body: bytes
) -> None:
    envelope = _envelope(status=status, body=body)
    path = _publish(tmp_path, envelope)

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())

    assert result.decision is Decision.REPLAYABLE
    assert result.envelope == envelope
    assert path.read_bytes() == envelope.to_bytes()


def test_run_is_path_binding_only(tmp_path: Path) -> None:
    envelope = _envelope()
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(envelope.to_bytes())

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())

    assert result.decision is Decision.REPLAYABLE
    assert result.envelope == envelope


@pytest.mark.parametrize(
    ("envelope", "inspection_request"),
    [
        (_envelope(selected="1002"), _request()),
        (_envelope(target="1002"), _request()),
    ],
)
def test_identity_mismatch_is_conflict(
    tmp_path: Path,
    envelope: ConfluenceRestrictionEvidenceEnvelope,
    inspection_request: ConfluenceRawRestrictionOrphanInspectionRequest,
) -> None:
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(envelope.to_bytes())

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=inspection_request)

    assert result.decision is Decision.IDENTITY_CONFLICT
    assert result.envelope is None


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, 201, 499])
def test_retryable_and_other_statuses_are_invalid(
    tmp_path: Path, status: int
) -> None:
    path = _target(tmp_path)
    path.parent.mkdir(parents=True)
    payload = json.loads(_envelope().to_bytes())
    payload["http_status"] = status
    path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.INVALID


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(request_profile_version="other"),
        lambda payload: payload.update(body_byte_count=99),
        lambda payload: payload.update(body_sha256="0" * 64),
        lambda payload: payload.update(body_base64="%%%"),
    ],
)
def test_malformed_or_noncanonical_evidence_is_invalid(tmp_path: Path, mutate) -> None:
    path = _publish(tmp_path, _envelope())
    payload = json.loads(path.read_bytes())
    mutate(payload)
    path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.INVALID


def test_duplicate_json_is_invalid(tmp_path: Path) -> None:
    path = _target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b'{"body_base64":"","body_base64":"","body_byte_count":0,'
        b'"body_encoding":"base64","body_sha256":"'
        + b"0" * 64
        + b'","evidence_kind":"confluence_restriction_observation",'
        b'"format_version":"1","http_status":200,"request_kind":"view_restriction",'
        b'"request_profile_version":"m7-confluence-request-profile-v1",'
        b'"selected_page_id":"1000","target_page_id":"1001"}'
    )
    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.INVALID


def test_non_regular_target_is_unsafe(tmp_path: Path) -> None:
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    target.mkdir()

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.UNSAFE_TARGET


def test_fifo_target_is_unsafe_without_opening(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    os.mkfifo(target)

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.UNSAFE_TARGET


def test_oversized_target_is_unsafe(tmp_path: Path) -> None:
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    with target.open("wb") as stream:
        stream.truncate(_MAX_STABLE_READ_BYTES + 1)

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.UNSAFE_TARGET


def test_disappearing_target_after_stat_is_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(tmp_path, _envelope())

    def _disappear(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(inspector_module, "_bound_read", _disappear)
    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.UNSAFE_TARGET


def test_unexpected_bound_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(tmp_path, _envelope())

    def _explode(*_args, **_kwargs):
        raise RuntimeError("private filesystem details")

    monkeypatch.setattr(inspector_module, "_bound_read", _explode)
    with pytest.raises(ConfluenceRawRestrictionOrphanInspectionError) as exc_info:
        ConfluenceRawRestrictionOrphanInspector(raw_root=tmp_path).inspect_restriction(
            request=_request()
        )
    assert exc_info.value.category is FailureCategory.INSPECTION_FAILED
    assert "private filesystem details" not in str(exc_info.value)


def test_parent_symlink_is_unsafe_when_supported(tmp_path: Path) -> None:
    base = tmp_path / "confluence" / "generations" / str(RUN_ID)
    base.mkdir(parents=True)
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    restrictions = base / "restrictions"
    try:
        restrictions.symlink_to(redirected, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.UNSAFE_TARGET


def test_target_symlink_is_unsafe_when_supported(tmp_path: Path) -> None:
    target = _target(tmp_path)
    target.parent.mkdir(parents=True)
    redirected = tmp_path / "redirected.json"
    redirected.write_bytes(_envelope().to_bytes())
    try:
        target.symlink_to(redirected)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = ConfluenceRawRestrictionOrphanInspector(
        raw_root=tmp_path
    ).inspect_restriction(request=_request())
    assert result.decision is Decision.UNSAFE_TARGET
