from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaAttachmentPublicationOutcome,
    MediaAttachmentRawArtifact,
    MediaBodyStoreBudget,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store import (
    ConfluenceRawAttachmentStore,
)
import knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store as raw_store_module
from knowledgenexus.foundation.ports.confluence_raw_attachment_store_port import (
    ConfluenceRawAttachmentStoreError,
)


def _budget(*, total: int = 1024 * 1024) -> MediaBodyStoreBudget:
    return MediaBodyStoreBudget(
        max_body_bytes=1024,
        max_total_bytes=total,
        minimum_free_disk_reserve_bytes=0,
    )


def _envelope(body: bytes = b"hello") -> MediaAttachmentBodyEnvelope:
    return MediaAttachmentBodyEnvelope(
        format_version="1",
        evidence_kind="confluence_attachment_body",
        attachment_id="123",
        parent_page_id="456",
        filename="hello.txt",
        source_version="v1",
        http_status=200,
        body_encoding="base64",
        body_bytes=body,
    )


def test_publish_read_and_replay_are_immutable(tmp_path: Path) -> None:
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    envelope = _envelope()

    first = store.publish_attachment(envelope=envelope)
    assert first.outcome is MediaAttachmentPublicationOutcome.PUBLISHED
    assert first.path == store.resolve_attachment_path(
        attachment_id="123", content_hash=hashlib.sha256(b"hello").hexdigest()
    )
    assert store.read_attachment(
        attachment_id="123", content_hash=first.body_sha256
    ) == envelope

    replay = store.publish_attachment(envelope=envelope)
    assert replay.outcome is MediaAttachmentPublicationOutcome.REUSED
    assert replay.path == first.path


def test_conflicting_replay_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    original = _envelope(b"first")
    store.publish_attachment(envelope=original)

    # The path is keyed by the body digest, so a mismatched envelope under an
    # existing target is simulated by replacing the final bytes directly.
    target = store.resolve_attachment_path(
        attachment_id="123", content_hash=hashlib.sha256(b"first").hexdigest()
    )
    target.write_bytes(
        MediaAttachmentBodyEnvelope(
            format_version="1",
            evidence_kind="confluence_attachment_body",
            attachment_id="123",
            parent_page_id="456",
            filename="different.txt",
            source_version="v1",
            http_status=200,
            body_encoding="base64",
            body_bytes=b"first",
        ).to_bytes()
    )
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.publish_attachment(envelope=original)
    assert exc_info.value.category == "raw_replay_conflict"


def test_root_and_path_components_are_strict(tmp_path: Path) -> None:
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        ConfluenceRawAttachmentStore(data_root=tmp_path / "missing", budget=_budget())
    assert exc_info.value.category == "raw_artifact_invalid"

    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    with pytest.raises(ConfluenceRawAttachmentStoreError):
        store.resolve_attachment_path(attachment_id="../1", content_hash="0" * 64)
    with pytest.raises(ConfluenceRawAttachmentStoreError):
        store.resolve_attachment_path(attachment_id="1", content_hash="A" * 64)


def test_budget_accounts_for_serialized_envelope(tmp_path: Path) -> None:
    envelope = _envelope()
    budget = MediaBodyStoreBudget(
        max_body_bytes=1,
        max_total_bytes=len(envelope.to_bytes()) - 1,
        minimum_free_disk_reserve_bytes=0,
    )
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=budget)
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.publish_attachment(envelope=envelope)
    assert exc_info.value.category == "budget_exceeded"


def test_symlinked_attachment_directory_fails_closed(tmp_path: Path) -> None:
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    attachments = tmp_path / "confluence" / "attachments"
    attachments.mkdir(parents=True)
    try:
        (attachments / "123").symlink_to(redirected, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.publish_attachment(envelope=_envelope())
    assert exc_info.value.category == "raw_artifact_invalid"


def test_forged_budget_and_envelope_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfluenceRawAttachmentStoreError) as budget_error:
        ConfluenceRawAttachmentStore(
            data_root=tmp_path,
            budget=object.__new__(MediaBodyStoreBudget),
        )
    assert budget_error.value.category == "raw_artifact_invalid"

    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    with pytest.raises(ConfluenceRawAttachmentStoreError) as envelope_error:
        store.publish_attachment(envelope=object.__new__(MediaAttachmentBodyEnvelope))
    assert envelope_error.value.category == "raw_artifact_invalid"


def test_scan_failure_is_mapped_to_sanitized_category(tmp_path: Path, monkeypatch) -> None:
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    monkeypatch.setattr(raw_store_module, "_scan_tree", lambda _: (_ for _ in ()).throw(RuntimeError("secret/path")))
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.publish_attachment(envelope=_envelope())
    assert exc_info.value.category == "raw_artifact_invalid"
    assert "secret/path" not in repr(exc_info.value)


def test_replaced_data_root_after_scan_fails_closed(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data-root"
    data_root.mkdir()
    store = ConfluenceRawAttachmentStore(data_root=data_root, budget=_budget())
    original = data_root
    moved = tmp_path / "moved-root"

    def replace_root(_: Path) -> int:
        original.rename(moved)
        original.mkdir()
        return 0

    monkeypatch.setattr(raw_store_module, "_scan_tree", replace_root)
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.publish_attachment(envelope=_envelope())
    assert exc_info.value.category == "raw_artifact_invalid"


def test_replay_scans_sibling_entries_before_reusing(tmp_path: Path) -> None:
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    envelope = _envelope()
    first = store.publish_attachment(envelope=envelope)
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    sibling = first.path.parent / "unsafe-link"
    try:
        sibling.symlink_to(redirected, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.publish_attachment(envelope=envelope)
    assert exc_info.value.category == "raw_artifact_invalid"


def test_hardlinked_target_fails_closed(tmp_path: Path) -> None:
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    first = store.publish_attachment(envelope=_envelope())
    outside = tmp_path / "outside-link"
    try:
        outside.hardlink_to(first.path)
    except (OSError, NotImplementedError):
        pytest.skip("hardlink creation is unavailable")
    with pytest.raises(ConfluenceRawAttachmentStoreError) as exc_info:
        store.read_attachment(attachment_id="123", content_hash=first.body_sha256)
    assert exc_info.value.category == "raw_artifact_invalid"


def test_concurrent_publishes_reserve_cumulative_budget(tmp_path: Path) -> None:
    first = _envelope(b"first")
    second = MediaAttachmentBodyEnvelope(
        format_version="1",
        evidence_kind="confluence_attachment_body",
        attachment_id="124",
        parent_page_id="456",
        filename="hello.txt",
        source_version="v1",
        http_status=200,
        body_encoding="base64",
        body_bytes=b"second",
    )
    budget = MediaBodyStoreBudget(
        max_body_bytes=100,
        max_total_bytes=len(first.to_bytes()),
        minimum_free_disk_reserve_bytes=0,
    )
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=budget)

    def publish(envelope: MediaAttachmentBodyEnvelope):
        try:
            return store.publish_attachment(envelope=envelope)
        except ConfluenceRawAttachmentStoreError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, (first, second)))
    assert sum(isinstance(result, MediaAttachmentRawArtifact) for result in results) == 1
    failures = [result for result in results if isinstance(result, ConfluenceRawAttachmentStoreError)]
    assert len(failures) == 1
    assert failures[0].category == "budget_exceeded"


def test_equivalent_resolved_roots_share_publish_lock(tmp_path: Path) -> None:
    first = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=_budget())
    second = ConfluenceRawAttachmentStore(data_root=tmp_path.resolve(), budget=_budget())
    assert first._publish_lock is second._publish_lock
