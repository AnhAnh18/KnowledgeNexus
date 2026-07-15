from __future__ import annotations

from collections.abc import Iterable

import pytest

from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from tests.fixtures.foundation import record_factories
from tests.fixtures.foundation.sample_record_set import build_sample_record_set


SCHEMA_BY_COLLECTION = {
    "documents": "CanonicalDocument",
    "chunks": "ChunkRecord",
    "relations": "RelationRecord",
    "acl_records": "ACLRecord",
}


ID_FIELD_BY_COLLECTION = {
    "documents": "document_id",
    "chunks": "chunk_id",
    "relations": "relation_id",
    "acl_records": "acl_id",
}


def test_all_sample_records_pass_foundation_schema_validation() -> None:
    validator = FoundationSchemaValidator()
    record_set = build_sample_record_set()

    for collection_name, schema_name in SCHEMA_BY_COLLECTION.items():
        for record in record_set[collection_name]:
            validator.validate_record(schema_name, record)


def test_chunks_and_acl_records_reference_existing_documents() -> None:
    record_set = build_sample_record_set()
    document_ids = _ids(record_set["documents"], "document_id")

    assert _ids(record_set["chunks"], "document_id") <= document_ids
    assert _ids(record_set["acl_records"], "document_id") <= document_ids


def test_chunk_relation_ids_reference_existing_relations() -> None:
    record_set = build_sample_record_set()
    relation_ids = _ids(record_set["relations"], "relation_id")

    for chunk in record_set["chunks"]:
        assert set(chunk["relation_ids"]) <= relation_ids


def test_chunk_acl_tags_are_compatible_with_acl_record() -> None:
    record_set = build_sample_record_set()
    acl_tags_by_document_id = {
        acl_record["document_id"]: set(acl_record["acl_tags"])
        for acl_record in record_set["acl_records"]
    }

    for chunk in record_set["chunks"]:
        assert set(chunk["acl_tags"]) <= acl_tags_by_document_id[chunk["document_id"]]


def test_record_ids_are_unique_within_each_record_type() -> None:
    record_set = build_sample_record_set()

    for collection_name, id_field in ID_FIELD_BY_COLLECTION.items():
        values = [record[id_field] for record in record_set[collection_name]]
        assert len(values) == len(set(values))


def test_sample_record_set_is_deterministic() -> None:
    assert build_sample_record_set() == build_sample_record_set()


def test_sample_records_do_not_share_mutable_lists_between_builds() -> None:
    first = build_sample_record_set()
    second = build_sample_record_set()

    first["documents"][0]["relation_ids"].append(  # type: ignore[attr-defined]
        "rel:1111111111111111"
    )
    first["chunks"][0]["acl_tags"].append(  # type: ignore[attr-defined]
        "space:OTHER"
    )
    first["chunks"][0]["relation_ids"].append(  # type: ignore[attr-defined]
        "rel:2222222222222222"
    )
    first["acl_records"][0]["acl_tags"].append(  # type: ignore[attr-defined]
        "space:OTHER"
    )

    assert second["documents"][0]["relation_ids"] != first["documents"][0][
        "relation_ids"
    ]
    assert second["chunks"][0]["acl_tags"] != first["chunks"][0]["acl_tags"]
    assert second["chunks"][0]["relation_ids"] != first["chunks"][0]["relation_ids"]
    assert second["acl_records"][0]["acl_tags"] != first["acl_records"][0][
        "acl_tags"
    ]


def test_equal_acl_tag_values_are_not_the_same_list_object() -> None:
    record_set = build_sample_record_set()
    chunk_acl_tags = record_set["chunks"][0]["acl_tags"]
    acl_record_tags = record_set["acl_records"][0]["acl_tags"]

    assert chunk_acl_tags == acl_record_tags
    assert chunk_acl_tags is not acl_record_tags


def test_record_factories_delegate_to_existing_record_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_document_build(**_: object) -> dict[str, object]:
        calls.append("document")
        return {"kind": "document"}

    def fake_chunk_build(**_: object) -> dict[str, object]:
        calls.append("chunk")
        return {"kind": "chunk"}

    def fake_relation_build(**_: object) -> dict[str, object]:
        calls.append("relation")
        return {"kind": "relation"}

    def fake_acl_build(**_: object) -> dict[str, object]:
        calls.append("acl")
        return {"kind": "acl"}

    monkeypatch.setattr(
        record_factories.CanonicalDocumentRecordBuilder,
        "build",
        staticmethod(fake_document_build),
    )
    monkeypatch.setattr(
        record_factories.ChunkRecordBuilder,
        "build",
        staticmethod(fake_chunk_build),
    )
    monkeypatch.setattr(
        record_factories.RelationRecordBuilder,
        "build",
        staticmethod(fake_relation_build),
    )
    monkeypatch.setattr(
        record_factories.ACLRecordBuilder,
        "build",
        staticmethod(fake_acl_build),
    )

    assert record_factories.build_sample_document_record() == {"kind": "document"}
    assert record_factories.build_sample_chunk_record() == {"kind": "chunk"}
    assert record_factories.build_sample_relation_record() == {"kind": "relation"}
    assert record_factories.build_sample_acl_record() == {"kind": "acl"}
    assert calls == ["document", "chunk", "relation", "acl"]


def _ids(records: Iterable[dict[str, object]], field_name: str) -> set[object]:
    return {record[field_name] for record in records}
