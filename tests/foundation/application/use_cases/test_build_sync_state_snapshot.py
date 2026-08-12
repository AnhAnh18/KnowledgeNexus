from __future__ import annotations

import pytest

from knowledgenexus.foundation.application.use_cases import (
    BuildSyncStateSnapshot,
    SyncStateSnapshotError,
)


def _page() -> dict[str, object]:
    return {
        "document_id": "confluence:page:1000",
        "source_system": "confluence",
        "source_version": "7",
        "content_hash": "a" * 64,
    }


def test_projects_page_attachment_and_repo_rows_deterministically() -> None:
    result = BuildSyncStateSnapshot().execute(
        source_id="SVMC",
        synced_at="2026-08-08T00:00:00Z",
        documents=(_page(),),
        media_assets=(
            {
                "media_id": "confluence:attachment:2000",
                "source_system": "confluence",
                "source_version": "7",
                "content_hash": None,
            },
        ),
        repository_id="spen-sdk",
    )
    assert [row["entity_type"] for row in result.records] == ["attachment", "page", "repo"]
    assert result.records[1]["last_seen_version"] == "7"


def test_rejects_duplicate_entity_ids_and_wrong_stream_types() -> None:
    with pytest.raises(SyncStateSnapshotError):
        BuildSyncStateSnapshot().execute(
            source_id="SVMC",
            synced_at="2026-08-08T00:00:00Z",
            documents=(_page(), _page()),
        )
    with pytest.raises(SyncStateSnapshotError):
        BuildSyncStateSnapshot().execute(
            source_id="SVMC",
            synced_at="2026-08-08T00:00:00Z",
            documents=({"document_id": "bad", "source_system": "other"},),
        )


@pytest.mark.parametrize("value", [None, object(), []])
def test_rejects_wrong_runtime_inputs(value: object) -> None:
    with pytest.raises(SyncStateSnapshotError):
        BuildSyncStateSnapshot().execute(
            source_id="SVMC",
            synced_at="2026-08-08T00:00:00Z",
            documents=value,
        )


def test_authoritative_inventory_must_cover_exact_emitted_entities() -> None:
    page = _page()
    inventory = ({
        "source_id": "SVMC",
        "entity_id": page["document_id"],
        "entity_type": "page",
        "last_seen_version": "7",
        "last_content_hash": page["content_hash"],
        "last_synced_at": "2026-08-08T00:00:00Z",
        "status": "active",
    },)
    result = BuildSyncStateSnapshot().execute(
        source_id="SVMC",
        synced_at="2026-08-08T00:00:00Z",
        documents=(page,),
        inventory=inventory,
    )
    assert result.records[0]["last_seen_version"] == "7"
    with pytest.raises(SyncStateSnapshotError, match="cover emitted"):
        BuildSyncStateSnapshot().execute(
            source_id="SVMC",
            synced_at="2026-08-08T00:00:00Z",
            documents=(page,),
            inventory=(),
        )
