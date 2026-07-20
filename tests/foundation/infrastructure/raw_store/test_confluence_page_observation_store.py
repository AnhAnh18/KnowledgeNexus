from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluencePageObservationStore,
    ConfluenceRawObservationStoreError,
    ConfluenceRawPageReadError,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    confluence_page_observation_store as store_module,
)


def _store(root: Path) -> ConfluencePageObservationStore:
    return ConfluencePageObservationStore(raw_root=root)


def test_reads_deterministic_m6a_raw_page_exactly(tmp_path: Path) -> None:
    target = tmp_path / "confluence" / "pages" / "1000.json"
    target.parent.mkdir(parents=True)
    raw = b'{"id":"1000"}  \n'
    target.write_bytes(raw)

    assert _store(tmp_path).read_page(page_id="1000") == raw


def test_missing_raw_page_raises_sanitized_port_error(tmp_path: Path) -> None:
    with pytest.raises(ConfluenceRawPageReadError) as exc_info:
        _store(tmp_path).read_page(page_id="1000")
    assert "1000" not in str(exc_info.value)


@pytest.mark.parametrize("raw", [b"", b"<html>unavailable</html>", b'{"x":1}\n'])
def test_preserves_restriction_body_exactly(tmp_path: Path, raw: bytes) -> None:
    artifact = _store(tmp_path).write_restriction(
        selected_page_id="1000",
        target_page_id="900",
        raw_bytes=raw,
    )
    assert artifact.path == (
        tmp_path.resolve()
        / "confluence"
        / "restrictions"
        / "view"
        / "1000"
        / "900.body"
    )
    assert artifact.path.read_bytes() == raw
    assert artifact.raw_sha256 == hashlib.sha256(raw).hexdigest()


def test_preserves_attachment_window_at_actual_request_path(tmp_path: Path) -> None:
    raw = b'{"results":[]}  \n'
    artifact = _store(tmp_path).write_attachment_window(
        selected_page_id="1000",
        request=AttachmentMetadataRequest(start=7, limit=3),
        raw_bytes=raw,
    )
    assert artifact.path == (
        tmp_path.resolve()
        / "confluence"
        / "attachments"
        / "metadata"
        / "1000"
        / "start-7_limit-3.json"
    )
    assert artifact.path.read_bytes() == raw
    assert "1000" not in repr(artifact)
    assert artifact.raw_sha256 not in repr(artifact)


def test_atomic_replace_failure_preserves_prior_and_cleans_owned_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    prior = store.write_restriction(
        selected_page_id="1000",
        target_page_id="900",
        raw_bytes=b"prior",
    )
    bystander = prior.path.parent / "unrelated.keep"
    bystander.write_bytes(b"unrelated")

    def boom(source: object, target: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(store_module.os, "replace", boom)
    with pytest.raises(ConfluenceRawObservationStoreError):
        store.write_restriction(
            selected_page_id="1000",
            target_page_id="900",
            raw_bytes=b"new",
        )

    assert prior.path.read_bytes() == b"prior"
    assert bystander.read_bytes() == b"unrelated"
    assert sorted(path.name for path in prior.path.parent.iterdir()) == [
        "900.body",
        "unrelated.keep",
    ]


def test_fsync_failure_removes_only_task_owned_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "confluence" / "attachments" / "metadata" / "1000"
    folder.mkdir(parents=True)
    bystander = folder / "unrelated.keep"
    bystander.write_bytes(b"unrelated")

    def boom(fd: int) -> None:
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(store_module.os, "fsync", boom)
    with pytest.raises(ConfluenceRawObservationStoreError):
        _store(tmp_path).write_attachment_window(
            selected_page_id="1000",
            request=AttachmentMetadataRequest(start=0, limit=2),
            raw_bytes=b"new",
        )

    assert bystander.read_bytes() == b"unrelated"
    assert sorted(path.name for path in folder.iterdir()) == ["unrelated.keep"]
