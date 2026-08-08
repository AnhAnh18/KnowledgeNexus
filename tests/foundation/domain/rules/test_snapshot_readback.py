from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules.snapshot_readback import (
    SnapshotReadbackError,
    validate_snapshot_streams,
)
from tests.fixtures.foundation.record_factories import (
    build_sample_acl_record,
    build_sample_chunk_record,
    build_sample_document_record,
    build_sample_relation_record,
)


def _streams() -> dict[str, tuple[dict[str, object], ...]]:
    document = build_sample_document_record()
    chunk = build_sample_chunk_record()
    acl = build_sample_acl_record()
    relation = build_sample_relation_record()
    sync = {
        "schema_version": "1.0",
        "source_id": "confluence",
        "entity_id": document["document_id"],
        "entity_type": "page",
        "last_seen_version": "1",
        "last_content_hash": document["content_hash"],
        "last_synced_at": "2026-07-10T00:00:00Z",
        "status": "active",
    }
    return {
        "documents": (document,),
        "chunks": (chunk,),
        "relations": (relation,),
        "acl": (acl,),
        "media_assets": (),
        "symbols": (),
        "sync_state": (sync,),
        "tombstones": (),
    }


def test_readback_closes_all_foundation_streams() -> None:
    report = validate_snapshot_streams(_streams(), export_mode="full_snapshot")
    assert report.relation_closed and report.acl_closed and report.sync_closed
    assert dict(report.stream_counts)["documents"] == 1


def test_readback_rejects_orphan_chunk() -> None:
    streams = _streams()
    orphan = dict(streams["chunks"][0], document_id="confluence:page:missing")
    streams["chunks"] = (orphan,)
    with pytest.raises(SnapshotReadbackError, match="chunk parent"):
        validate_snapshot_streams(streams, export_mode="full_snapshot")


def test_delta_readback_rejects_tombstone_outside_prior_snapshot() -> None:
    streams = _streams()
    streams["tombstones"] = ({
        "tombstone_id": "tombstone:missing",
        "entity_type": "document",
        "entity_id": "confluence:page:missing",
        "reason": "source_deleted",
        "detail": None,
        "detected_at": "2026-07-11T00:00:00Z",
        "dataset_version": "v20260711-000000-000000Z",
        "source_version_last_seen": None,
    },)
    with pytest.raises(SnapshotReadbackError, match="prior snapshot"):
        validate_snapshot_streams(streams, export_mode="delta", prior_streams=_streams())
