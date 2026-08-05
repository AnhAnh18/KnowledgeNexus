from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest
import knowledgenexus.foundation.domain.rules.chunk_stability_builder as chunk_stability_builder_module

from knowledgenexus.foundation.domain.models import (
    ACTIVE_CHUNKER_VERSION,
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ChunkStabilityEntry,
    ChunkStabilityError,
    ChunkStabilityFailureCategory,
    DocumentChunkSetSummary,
    ConfluencePageSetMetrics,
    ConfluencePageSetPageMetrics,
    ConfluencePageSetResult,
)
from knowledgenexus.foundation.domain.records import (
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import (
    ChunkIdGenerator,
    ChunkStabilitySummaryBuilder,
    ContentHasher,
)


def _document(*, document_id: str = "confluence:page:1000", body: str = "body") -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id=document_id,
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=body,
        acl_id="acl:confluence:page:1000",
        crawled_at="2026-08-04T00:00:00Z",
        title="Page",
        page_id="1000",
        source_version="7",
    )


def _chunk(
    document: dict[str, object],
    *,
    text: str = "chunk text",
    kind: str = "prose",
    unit: str = "h1",
    part_index: int | None = None,
    part_total: int | None = None,
) -> dict[str, object]:
    document_id = document["document_id"]
    assert isinstance(document_id, str)
    return ChunkRecordBuilder.build(
        chunk_id=ChunkIdGenerator.generate_chunk_id("confluence", document_id, unit, text),
        document_id=document_id,
        source_system="confluence",
        source_type="wiki_page",
        text=text,
        content_kind=kind,
        language="unknown",
        token_count=2,
        acl_tags=["restricted:unresolved"],
        chunker_version=ACTIVE_CHUNKER_VERSION,
        title="Page",
        page_id="1000",
        source_version="7",
        part_index=part_index,
        part_total=part_total,
    )


def test_entry_and_summary_are_immutable_and_canonical() -> None:
    entry = ChunkStabilityEntry(
        chunk_id="chunk:confluence:0123456789abcdef",
        content_hash="a" * 64,
        content_kind="prose",
        token_count=2,
    )
    summary = DocumentChunkSetSummary(
        format_version="1",
        document_id="confluence:page:1000",
        document_content_hash="b" * 64,
        chunker_version=ACTIVE_CHUNKER_VERSION,
        profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        entries=(entry,),
        chunk_count=1,
        content_kind_counts=(("prose", 1),),
    )
    payload = summary.to_canonical_json()
    assert payload == summary.to_canonical_json()
    assert summary.digest == hashlib.sha256(payload).hexdigest()
    assert json.loads(payload)["entries"][0].keys() == {
        "chunk_id",
        "content_hash",
        "content_kind",
        "part_index",
        "part_total",
        "token_count",
    }
    with pytest.raises(FrozenInstanceError):
        entry.token_count = 3  # type: ignore[misc]


def test_builder_recomputes_chunk_hash_and_drops_text() -> None:
    document = _document()
    chunk = _chunk(document)
    summary = ChunkStabilitySummaryBuilder.build_document(
        canonical_document=document,
        chunks=(chunk,),
    )
    assert summary.chunk_count == 1
    assert summary.entries[0].content_hash == ContentHasher.hash_text("chunk text")
    assert b"chunk text" not in summary.to_canonical_json()
    assert b"title" not in summary.to_canonical_json()

    chunk["text"] = "changed"
    assert summary.entries[0].content_hash != ContentHasher.hash_text(chunk["text"])


@pytest.mark.parametrize(
    "bad_document,bad_chunks,category",
    [
        (None, (), ChunkStabilityFailureCategory.INVALID_INPUT),
        (object(), (), ChunkStabilityFailureCategory.INVALID_INPUT),
    ],
)
def test_builder_rejects_wrong_boundary_types(bad_document, bad_chunks, category) -> None:
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=bad_document,
            chunks=bad_chunks,
        )
    assert exc_info.value.category == category
    assert "object at" not in str(exc_info.value)


def test_builder_rejects_hash_profile_duplicates_and_cross_document() -> None:
    document = _document()
    chunk = _chunk(document)
    bad_hash = dict(chunk)
    bad_hash["content_hash"] = "a" * 64
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(bad_hash,),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.CHUNK_INVALID

    bad_profile = dict(chunk)
    bad_profile["chunker_version"] = "9.9.9"
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(bad_profile,),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.PROFILE_MISMATCH

    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(chunk, dict(chunk)),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.DUPLICATE_ID

    other = _document(document_id="confluence:page:2000")
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(_chunk(other),),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.CROSS_DOCUMENT_MISMATCH


@pytest.mark.parametrize(
    "mutator,expected_category",
    [
        (lambda value: value.update({"unexpected": "nope"}), ChunkStabilityFailureCategory.SCHEMA_INVALID),
        (lambda value: value.update({"content_kind": "not-a-kind"}), ChunkStabilityFailureCategory.SCHEMA_INVALID),
        (lambda value: value.update({"token_count": True}), ChunkStabilityFailureCategory.SCHEMA_INVALID),
    ],
)
def test_builder_rejects_schema_and_runtime_contract_drift(mutator, expected_category) -> None:
    document = _document()
    chunk = _chunk(document)
    mutator(chunk)
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(chunk,),
        )
    assert exc_info.value.category == expected_category


def test_models_reject_none_object_bool_and_impossible_counters() -> None:
    with pytest.raises((TypeError, ValueError)):
        ChunkStabilityEntry(object(), "a" * 64, "prose", 0)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        ChunkStabilityEntry("chunk:confluence:0123456789abcdef", "a" * 64, "prose", True)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        DocumentChunkSetSummary(
            format_version="1",
            document_id="confluence:page:1000",
            document_content_hash="a" * 64,
            chunker_version=ACTIVE_CHUNKER_VERSION,
            profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
            entries=(),
            chunk_count=1,
            content_kind_counts=(),
        )


def test_builder_is_all_or_nothing_and_errors_are_sanitized() -> None:
    document = _document()
    good = _chunk(document, unit="good")
    bad = _chunk(document, unit="bad")
    bad["text"] = "tampered"
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(good, bad),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.CHUNK_INVALID
    assert "tampered" not in str(exc_info.value)
    assert "good" not in repr(exc_info.value)


def test_builder_sanitizes_hostile_validator_attribute_lookup() -> None:
    class HostileValidator:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("SECRET VALIDATOR")

    document = _document()
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(),
            schema_validator=HostileValidator(),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.INVALID_INPUT
    assert "SECRET" not in str(exc_info.value)


def test_builder_sanitizes_validator_construction_failure(monkeypatch) -> None:
    calls: list[str] = []

    def fail_constructor():
        calls.append("ctor")
        raise RuntimeError("SECRET INIT")

    monkeypatch.setattr(
        chunk_stability_builder_module,
        "FoundationSchemaValidator",
        fail_constructor,
    )
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=None,
            chunks=(),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.INVALID_INPUT
    assert "SECRET" not in str(exc_info.value)
    assert calls == []

    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=_document(),
            chunks=(),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.INVALID_INPUT
    assert "SECRET" not in str(exc_info.value)
    assert calls == ["ctor"]


def test_builder_rejects_malicious_string_subclasses_at_identity_boundary() -> None:
    class EvilStr(str):
        def __eq__(self, other: object) -> bool:
            return True

    document = _document()
    chunk = _chunk(document)
    chunk["document_id"] = EvilStr(document["document_id"])
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(chunk,),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.CHUNK_INVALID


@pytest.mark.parametrize(
    "part_values,expected_category",
    [
        ((0, None), ChunkStabilityFailureCategory.ORDER_INVALID),
        ((None, 2), ChunkStabilityFailureCategory.ORDER_INVALID),
        ((-1, 2), ChunkStabilityFailureCategory.SCHEMA_INVALID),
        ((2, 2), ChunkStabilityFailureCategory.ORDER_INVALID),
    ],
)
def test_builder_rejects_impossible_part_metadata(part_values, expected_category) -> None:
    document = _document()
    chunk = _chunk(document, part_index=part_values[0], part_total=part_values[1])
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(chunk,),
        )
    assert exc_info.value.category == expected_category


def test_builder_accepts_valid_suffix_and_requires_contiguous_parts() -> None:
    document = _document()
    first = _chunk(document, text="same", unit="one", part_index=0, part_total=2)
    second = _chunk(document, text="same", unit="two", part_index=1, part_total=2)
    second["chunk_id"] = f"{first['chunk_id']}-1"
    summary = ChunkStabilitySummaryBuilder.build_document(
        canonical_document=document,
        chunks=(first, second),
    )
    assert [entry.part_index for entry in summary.entries] == [0, 1]

    gap = dict(second)
    gap["part_index"] = 0
    gap["chunk_id"] = f"{first['chunk_id']}-2"
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_document(
            canonical_document=document,
            chunks=(first, gap),
        )
    assert exc_info.value.category == ChunkStabilityFailureCategory.ORDER_INVALID


def test_builder_accepts_single_part_metadata() -> None:
    document = _document()
    chunk = _chunk(document, part_index=0, part_total=1)
    summary = ChunkStabilitySummaryBuilder.build_document(
        canonical_document=document,
        chunks=(chunk,),
    )
    assert summary.entries[0].part_index == 0
    assert summary.entries[0].part_total == 1


def test_page_set_adapter_preserves_document_order_and_allows_empty_document() -> None:
    first = _document(document_id="confluence:page:1000")
    second = _document(document_id="confluence:page:2000")
    first_chunk = _chunk(first, unit="first")
    result = ConfluencePageSetResult(
        documents=(first, second),
        chunks=(first_chunk,),
        page_metrics=(
            ConfluencePageSetPageMetrics(
                page_ordinal=1,
                chunk_count=1,
                warning_count=0,
                reference_intent_count=0,
                content_kind_counts=(("prose", 1),),
            ),
            ConfluencePageSetPageMetrics(
                page_ordinal=2,
                chunk_count=0,
                warning_count=0,
                reference_intent_count=0,
                content_kind_counts=(),
            ),
        ),
        metrics=ConfluencePageSetMetrics(
            requested_pages=2,
            succeeded_pages=2,
            failed_pages=0,
            document_count=2,
            chunk_count=1,
            warning_count=0,
            reference_intent_count=0,
            content_kind_counts=(("prose", 1),),
        ),
    )
    summaries = ChunkStabilitySummaryBuilder.build_page_set(result=result)
    assert [summary.document_id for summary in summaries] == [
        "confluence:page:1000",
        "confluence:page:2000",
    ]
    assert [summary.chunk_count for summary in summaries] == [1, 0]


def test_page_set_adapter_rejects_out_of_order_and_interleaved_chunks() -> None:
    first = _document(document_id="confluence:page:1000")
    second = _document(document_id="confluence:page:2000")
    first_chunk = _chunk(first, unit="first")
    second_chunk = _chunk(second, unit="second")

    result = ConfluencePageSetResult(
        documents=(first, second),
        chunks=(second_chunk, first_chunk),
        page_metrics=(
            ConfluencePageSetPageMetrics(1, 1, 0, 0, (("prose", 1),)),
            ConfluencePageSetPageMetrics(2, 1, 0, 0, (("prose", 1),)),
        ),
        metrics=ConfluencePageSetMetrics(2, 2, 0, 2, 2, 0, 0, (("prose", 2),)),
    )
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_page_set(result=result)
    assert exc_info.value.category == ChunkStabilityFailureCategory.ORDER_INVALID

    result = ConfluencePageSetResult(
        documents=(first, second),
        chunks=(first_chunk, second_chunk, _chunk(first, unit="third")),
        page_metrics=(
            ConfluencePageSetPageMetrics(1, 2, 0, 0, (("prose", 2),)),
            ConfluencePageSetPageMetrics(2, 1, 0, 0, (("prose", 1),)),
        ),
        metrics=ConfluencePageSetMetrics(2, 2, 0, 2, 3, 0, 0, (("prose", 3),)),
    )
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_page_set(result=result)
    assert exc_info.value.category == ChunkStabilityFailureCategory.ORDER_INVALID


def test_page_set_adapter_rejects_cross_document_duplicate_chunk_id() -> None:
    first = _document(document_id="confluence:page:1000")
    second = _document(document_id="confluence:page:2000")
    first_chunk = _chunk(first, unit="first")
    second_chunk = _chunk(second, unit="second")
    second_chunk["chunk_id"] = first_chunk["chunk_id"]
    result = ConfluencePageSetResult(
        documents=(first, second),
        chunks=(first_chunk, second_chunk),
        page_metrics=(
            ConfluencePageSetPageMetrics(1, 1, 0, 0, (("prose", 1),)),
            ConfluencePageSetPageMetrics(2, 1, 0, 0, (("prose", 1),)),
        ),
        metrics=ConfluencePageSetMetrics(2, 2, 0, 2, 2, 0, 0, (("prose", 2),)),
    )
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_page_set(result=result)
    assert exc_info.value.category == ChunkStabilityFailureCategory.DUPLICATE_ID


def test_page_set_adapter_sanitizes_bypassed_typed_result() -> None:
    malformed = object.__new__(ConfluencePageSetResult)
    with pytest.raises(ChunkStabilityError) as exc_info:
        ChunkStabilitySummaryBuilder.build_page_set(result=malformed)
    assert exc_info.value.category == ChunkStabilityFailureCategory.INVALID_INPUT
    assert "AttributeError" not in str(exc_info.value)
