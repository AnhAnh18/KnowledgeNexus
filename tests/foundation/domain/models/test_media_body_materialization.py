from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaAttachmentPublicationOutcome,
    MediaAttachmentRawArtifact,
    MediaBodyMaterializationError,
    MediaBodyMaterializationResult,
    MediaBodyStoreBudget,
)


def _envelope(body: bytes = b"body") -> MediaAttachmentBodyEnvelope:
    return MediaAttachmentBodyEnvelope(
        format_version="1",
        evidence_kind="confluence_attachment_body",
        attachment_id="2000",
        parent_page_id="1000",
        filename="diagram.drawio",
        source_version="4",
        http_status=200,
        body_encoding="base64",
        body_bytes=body,
    )


def _artifact(tmp_path: Path, body: bytes = b"body") -> MediaAttachmentRawArtifact:
    envelope = _envelope(body)
    digest = __import__("hashlib").sha256(body).hexdigest()
    return MediaAttachmentRawArtifact(
        path=tmp_path / "confluence" / "attachments" / "2000" / f"{digest}.json",
        attachment_id="2000",
        body_sha256=digest,
        byte_count=len(body),
        raw_uri=f"raw://confluence/attachments/2000/{digest}",
        outcome=MediaAttachmentPublicationOutcome.PUBLISHED,
    )


def test_budget_rejects_bool_and_impossible_relationships() -> None:
    with pytest.raises(TypeError):
        MediaBodyStoreBudget(max_body_bytes=True, max_total_bytes=10, minimum_free_disk_reserve_bytes=0)
    with pytest.raises(ValueError):
        MediaBodyStoreBudget(max_body_bytes=10, max_total_bytes=9, minimum_free_disk_reserve_bytes=0)


def test_envelope_is_canonical_and_round_trips() -> None:
    envelope = _envelope("cafe".encode())
    encoded = envelope.to_bytes()
    assert encoded == envelope.to_bytes()
    assert MediaAttachmentBodyEnvelope.from_bytes(encoded) == envelope
    assert b"\n" not in encoded


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(body_byte_count=99),
        lambda payload: payload.update(body_sha256="0" * 64),
        lambda payload: payload.update(body_base64="%%%"),
        lambda payload: payload.update(extra=True),
    ],
)
def test_envelope_rejects_tampering(mutator) -> None:
    payload = json.loads(_envelope().to_bytes())
    mutator(payload)
    with pytest.raises(ValueError):
        MediaAttachmentBodyEnvelope.from_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )


def test_result_validates_downloaded_status_and_defensively_copies(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    asset = {
        "schema_version": "1.0",
        "media_id": "confluence:attachment:2000",
        "parent_document_id": "confluence:page:1000",
        "source_system": "confluence",
        "filename": "diagram.drawio",
        "mime_type": "application/xml",
        "size_bytes": 4,
        "download_status": "downloaded",
        "processing_status": "not_processed",
        "relevance": "high",
        "extracted_text": None,
        "summary": None,
        "confidence": None,
        "raw_uri": artifact.raw_uri,
        "content_hash": artifact.body_sha256,
        "source_version": "4",
        "updated_at": None,
        "crawled_at": "2026-08-05T00:00:00Z",
    }
    result = MediaBodyMaterializationResult(asset=asset, artifact=artifact)
    asset["filename"] = "mutated"
    assert result.asset["filename"] == "diagram.drawio"


def test_result_rejects_impossible_status_or_hash(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    asset = {
        "schema_version": "1.0",
        "media_id": "confluence:attachment:2000",
        "parent_document_id": "confluence:page:1000",
        "source_system": "confluence",
        "filename": "diagram.drawio",
        "mime_type": None,
        "size_bytes": 4,
        "download_status": "skipped",
        "processing_status": "not_processed",
        "relevance": "high",
        "extracted_text": None,
        "summary": None,
        "confidence": None,
        "raw_uri": artifact.raw_uri,
        "content_hash": artifact.body_sha256,
        "source_version": None,
        "updated_at": None,
        "crawled_at": "2026-08-05T00:00:00Z",
    }
    with pytest.raises(ValueError):
        MediaBodyMaterializationResult(asset=asset, artifact=artifact)


def test_result_rejects_forged_artifact_without_leaking_attribute_errors(tmp_path: Path) -> None:
    artifact = object.__new__(MediaAttachmentRawArtifact)
    with pytest.raises(ValueError, match="media body result is invalid"):
        MediaBodyMaterializationResult(asset={}, artifact=artifact)


def test_raw_artifact_repr_excludes_byte_count(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    rendered = repr(artifact)
    assert "byte_count" not in rendered
    assert rendered == "MediaAttachmentRawArtifact()"
