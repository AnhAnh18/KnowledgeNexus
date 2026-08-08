from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.records import SyncStateRecordBuilder


def _build(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "source_id": "SVMC",
        "entity_id": "confluence:page:1000",
        "entity_type": "page",
        "last_seen_version": "7",
        "last_content_hash": "a" * 64,
        "last_synced_at": "2026-08-08T00:00:00Z",
        "status": "active",
    }
    fields.update(overrides)
    return SyncStateRecordBuilder.build(**fields)


def test_builds_schema_valid_page_state() -> None:
    record = _build()
    assert record["schema_version"] == "1.0"
    assert record["entity_id"] == "confluence:page:1000"
    assert record["status"] == "active"


@pytest.mark.parametrize(
    "field,value",
    [
        ("entity_type", "unknown"),
        ("status", "finished"),
        ("last_content_hash", "not-a-hash"),
        ("last_synced_at", "not-a-timestamp"),
        ("source_id", ""),
    ],
)
def test_rejects_invalid_field_values(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _build(**{field: value})


def test_rejects_wrong_runtime_types_before_validator_access() -> None:
    class HostileValidator:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("validator should not be reached")

    with pytest.raises((TypeError, ValueError)):
        SyncStateRecordBuilder.build(
            source_id="SVMC",
            entity_id="confluence:page:1000",
            entity_type=object(),  # type: ignore[arg-type]
            last_synced_at="2026-08-08T00:00:00Z",
            schema_validator=HostileValidator(),
        )


def test_validator_is_required_to_be_callable() -> None:
    with pytest.raises(TypeError):
        _build(schema_validator=object())
