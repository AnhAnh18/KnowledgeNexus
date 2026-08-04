from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_orphan_inspection import (
    ConfluenceRawPageOrphanInspectionDecision as Decision,
    ConfluenceRawPageOrphanInspectionRequest,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
    ConfluenceRawPageOrphanInspector,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    confluence_raw_page_orphan_inspector as inspector_module,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
    _MAX_STABLE_READ_BYTES,
)

RUN_ID = CrawlRunId("12345678-1234-4234-9234-123456789abc")
OTHER_RUN_ID = CrawlRunId("87654321-4321-4234-9234-cba987654321")


def _envelope(
    *,
    run_id: CrawlRunId = RUN_ID,
    page_id: str = "1000",
    source_version: str | None = "v1",
    body: bytes = b"body",
) -> ConfluenceRawPageEnvelope:
    return ConfluenceRawPageEnvelope.capture(
        run_id=run_id,
        page_id=page_id,
        source_version=source_version,
        http_status=200,
        body_bytes=body,
    )


def _request(
    *,
    run_id: CrawlRunId = RUN_ID,
    generation_id: CrawlRunId = RUN_ID,
    page_id: str = "1000",
    source_version: str | None = "v1",
) -> ConfluenceRawPageOrphanInspectionRequest:
    return ConfluenceRawPageOrphanInspectionRequest.capture(
        run_id=run_id,
        generation_id=generation_id,
        page_id=page_id,
        source_version=source_version,
    )


def _publish(tmp_path: Path, envelope: ConfluenceRawPageEnvelope) -> Path:
    store = ConfluenceRawPageGenerationStore(raw_root=tmp_path)
    return store.publish_page(envelope=envelope).path


def test_missing_parent_is_read_only(tmp_path: Path) -> None:
    inspector = ConfluenceRawPageOrphanInspector(raw_root=tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = inspector.inspect_raw_page(request=_request())

    assert result.decision is Decision.MISSING
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


def test_missing_target_is_read_only(tmp_path: Path) -> None:
    target_parent = tmp_path / "confluence" / "generations" / str(RUN_ID) / "pages"
    target_parent.mkdir(parents=True)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.MISSING
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


@pytest.mark.parametrize("body", [b"", b"arbitrary\x00\xff body"])
def test_canonical_envelope_is_replayable(tmp_path: Path, body: bytes) -> None:
    envelope = _envelope(body=body)
    path = _publish(tmp_path, envelope)

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request(source_version=envelope.source_version)
    )

    assert result.decision is Decision.REPLAYABLE
    assert result.envelope == envelope
    assert path.read_bytes() == envelope.to_bytes()


@pytest.mark.parametrize(
    ("envelope", "inspection_request", "expected"),
    [
        (_envelope(run_id=OTHER_RUN_ID), _request(), Decision.IDENTITY_CONFLICT),
        (_envelope(page_id="1001"), _request(), Decision.IDENTITY_CONFLICT),
        (_envelope(source_version="v2"), _request(), Decision.IDENTITY_CONFLICT),
    ],
)
def test_canonical_identity_mismatches_are_conflicts(
    tmp_path: Path,
    envelope: ConfluenceRawPageEnvelope,
    inspection_request: ConfluenceRawPageOrphanInspectionRequest,
    expected: Decision,
) -> None:
    target = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(envelope.to_bytes())
    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=inspection_request
    )
    assert result.decision is expected


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(request_profile_version="other"),
        lambda payload: payload.update(generation_id=str(OTHER_RUN_ID)),
        lambda payload: payload.update(body_byte_count=99),
        lambda payload: payload.update(body_sha256="0" * 64),
        lambda payload: payload.update(body_base64="%%%"),
    ],
)
def test_malformed_or_noncanonical_envelope_is_invalid(tmp_path: Path, mutate) -> None:
    path = _publish(tmp_path, _envelope())
    payload = json.loads(path.read_bytes())
    mutate(payload)
    path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.INVALID


def test_non_regular_target_is_unsafe(tmp_path: Path) -> None:
    target = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )
    target.parent.mkdir(parents=True)
    target.mkdir()

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.UNSAFE_TARGET


def test_fifo_target_is_rejected_before_open_when_supported(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")
    target = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )
    target.parent.mkdir(parents=True)
    os.mkfifo(target)

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.UNSAFE_TARGET


def test_disappearing_target_after_stat_is_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(tmp_path, _envelope())

    def _disappear(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(inspector_module, "_bound_read", _disappear)
    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.UNSAFE_TARGET


def test_replacement_after_stat_is_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(tmp_path, _envelope(body=b"first"))
    target = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(_envelope(body=b"second").to_bytes())
    original_read = inspector_module._bound_read

    def _replace_then_read(parent_handle, name, **kwargs):
        os.replace(replacement, target)
        return original_read(parent_handle, name, **kwargs)

    monkeypatch.setattr(inspector_module, "_bound_read", _replace_then_read)
    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.UNSAFE_TARGET


def test_oversized_target_is_unsafe_without_reading_payload(tmp_path: Path) -> None:
    target = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )
    target.parent.mkdir(parents=True)
    with target.open("wb") as stream:
        stream.truncate(_MAX_STABLE_READ_BYTES + 1)
    before = target.stat().st_size

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.UNSAFE_TARGET
    assert target.stat().st_size == before


def test_symlink_target_is_unsafe_when_supported(tmp_path: Path) -> None:
    target = (
        tmp_path
        / "confluence"
        / "generations"
        / str(RUN_ID)
        / "pages"
        / "1000.json"
    )
    target.parent.mkdir(parents=True)
    redirected = tmp_path / "redirected.json"
    redirected.write_bytes(_envelope().to_bytes())
    try:
        target.symlink_to(redirected)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    result = ConfluenceRawPageOrphanInspector(raw_root=tmp_path).inspect_raw_page(
        request=_request()
    )

    assert result.decision is Decision.UNSAFE_TARGET
