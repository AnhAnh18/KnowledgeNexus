from dataclasses import FrozenInstanceError

import pytest

from knowledgenexus.foundation.domain.models import (
    ACTIVE_CHUNKER_VERSION,
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ChunkStabilityEntry,
    DeltaInventoryEntry,
    DeltaInventoryState,
    DeltaPropagationFailureCategory,
    DeltaPropagationMetrics,
    DeltaPropagationRequest,
    DeltaPropagationResult,
    DeltaPropagationStatus,
    DocumentChunkSetSummary,
    TombstoneEntityType,
    TombstoneTarget,
)


def _summary(document_id: str, document_hash: str = "a" * 64, entries=()) -> DocumentChunkSetSummary:
    entries = tuple(entries)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.content_kind] = counts.get(entry.content_kind, 0) + 1
    return DocumentChunkSetSummary(
        format_version="1",
        document_id=document_id,
        document_content_hash=document_hash,
        chunker_version=ACTIVE_CHUNKER_VERSION,
        profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        entries=entries,
        chunk_count=len(entries),
        content_kind_counts=tuple(sorted(counts.items())),
    )


def _entry(chunk_id: str, content_hash: str = "b" * 64) -> ChunkStabilityEntry:
    return ChunkStabilityEntry(chunk_id, content_hash, "prose", 1)


_SUMMARY_FIELDS = (
    "format_version", "document_id", "document_content_hash", "chunker_version",
    "profile_identity", "entries", "chunk_count", "content_kind_counts",
)


def _forged_summary(*, missing: str | None = None, extra: bool = False, entries=()) -> DocumentChunkSetSummary:
    # Keep malformed nested entries out of the baseline constructor so the
    # application boundary, rather than fixture setup, performs validation.
    valid = _summary("confluence:page:1")
    forged = object.__new__(DocumentChunkSetSummary)
    for field in _SUMMARY_FIELDS:
        if field == "entries":
            value = tuple(entries)
        else:
            value = getattr(valid, field)
        if field != missing:
            object.__setattr__(forged, field, value)
    if extra:
        object.__setattr__(forged, "extra", 1)
    return forged


def _forged_entry(*, missing: str | None = None, extra: bool = False, **overrides) -> ChunkStabilityEntry:
    valid = _entry("chunk:confluence:0123456789abcdef")
    forged = object.__new__(ChunkStabilityEntry)
    for field in ("chunk_id", "content_hash", "content_kind", "token_count", "part_index", "part_total"):
        if field != missing:
            object.__setattr__(forged, field, overrides.get(field, getattr(valid, field)))
    if extra:
        object.__setattr__(forged, "extra", 1)
    return forged


def test_request_validates_versions_hashes_timestamp_and_summary_identity() -> None:
    request = DeltaPropagationRequest(
        previous_dataset_version="base",
        current_dataset_version="next",
        previous_config_hash="a" * 64,
        current_config_hash="b" * 64,
        detected_at="2026-08-05T10:00:00+07:00",
        previous_summaries=(_summary("confluence:page:1"),),
        current_summaries=(),
    )
    assert request.detected_at == "2026-08-05T03:00:00.000000Z"
    with pytest.raises(FrozenInstanceError):
        request.current_dataset_version = "other"  # type: ignore[misc]

    with pytest.raises(ValueError):
        DeltaPropagationRequest(
            previous_dataset_version="same", current_dataset_version="same",
            previous_config_hash="a" * 64, current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z", previous_summaries=(), current_summaries=(),
        )


@pytest.mark.parametrize("value", [None, object(), "bad id"])
def test_inventory_entry_rejects_bad_document_id(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        DeltaInventoryEntry(value, DeltaInventoryState.PRESENT)  # type: ignore[arg-type]


def test_metrics_reject_impossible_cross_field_counts() -> None:
    with pytest.raises(ValueError):
        DeltaPropagationMetrics(1, 1, 1, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        DeltaPropagationMetrics(0, 0, 0, 0, 0, 1, 0, 1)


def test_failed_result_is_atomic() -> None:
    result = DeltaPropagationResult(
        status=DeltaPropagationStatus.FAILED,
        error_category=DeltaPropagationFailureCategory.INVALID_REQUEST,
    )
    assert result.records == () and result.count == 0 and result.metrics is None


def test_forged_metrics_do_not_match_document_outcomes() -> None:
    with pytest.raises(ValueError):
        DeltaPropagationResult(
            status=DeltaPropagationStatus.SUCCESS,
            base_dataset_version="base",
            dataset_version="next",
            records=(),
            count=0,
            metrics=DeltaPropagationMetrics(
                document_count=1,
                new_document_count=1,
                unchanged_document_count=0,
                changed_document_count=0,
                removed_document_count=0,
                document_tombstone_count=0,
                chunk_tombstone_count=0,
                record_count=0,
            ),
            digest="0" * 64,
            document_outcomes=(("confluence:page:1", "unchanged"),),
        )


def test_forged_missing_fields_fail_closed() -> None:
    forged = object.__new__(DeltaPropagationRequest)
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest.__post_init__(forged)


def test_forged_summary_extra_field_is_rejected() -> None:
    summary = _summary("confluence:page:1")
    object.__setattr__(summary, "extra", 1)
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base",
            current_dataset_version="next",
            previous_config_hash="a" * 64,
            current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z",
            previous_summaries=(summary,),
            current_summaries=(),
        )


def test_forged_nested_entry_hash_is_rejected() -> None:
    entry = _entry("chunk:confluence:0123456789abcdef")
    object.__setattr__(entry, "content_hash", "bad")
    summary = _summary("confluence:page:1", entries=(entry,))
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base",
            current_dataset_version="next",
            previous_config_hash="a" * 64,
            current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z",
            previous_summaries=(summary,),
            current_summaries=(),
        )


@pytest.mark.parametrize("missing", _SUMMARY_FIELDS)
def test_every_outer_summary_missing_field_is_rejected(missing: str) -> None:
    summary = _forged_summary(missing=missing)
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base", current_dataset_version="next",
            previous_config_hash="a" * 64, current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z", previous_summaries=(summary,), current_summaries=(),
        )


def test_outer_summary_forbidden_extra_field_is_rejected() -> None:
    summary = _forged_summary(extra=True)
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base", current_dataset_version="next",
            previous_config_hash="a" * 64, current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z", previous_summaries=(summary,), current_summaries=(),
        )


@pytest.mark.parametrize("missing", ("chunk_id", "content_hash", "content_kind", "token_count", "part_index", "part_total"))
def test_every_nested_entry_missing_field_is_rejected(missing: str) -> None:
    summary = _forged_summary(entries=(_forged_entry(missing=missing),))
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base", current_dataset_version="next",
            previous_config_hash="a" * 64, current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z", previous_summaries=(summary,), current_summaries=(),
        )


def test_nested_entry_forbidden_extra_field_is_rejected() -> None:
    summary = _forged_summary(entries=(_forged_entry(extra=True),))
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base", current_dataset_version="next",
            previous_config_hash="a" * 64, current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z", previous_summaries=(summary,), current_summaries=(),
        )


def test_current_dependents_and_reemit_records_validate_and_copy_inputs() -> None:
    summary = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    target = TombstoneTarget(TombstoneEntityType.MEDIA, "confluence:attachment:a1")
    acl = {"acl_id": "acl:confluence:page:1", "document_id": summary.document_id}
    chunk = {"chunk_id": summary.entries[0].chunk_id, "document_id": summary.document_id}
    request = DeltaPropagationRequest(
        previous_dataset_version="base", current_dataset_version="next",
        previous_config_hash="a" * 64, current_config_hash="b" * 64,
        detected_at="2026-08-05T00:00:00Z", previous_summaries=(summary,), current_summaries=(summary,),
        previous_dependents=((summary.document_id, (target,)),), current_dependents=((summary.document_id, (target,)),),
        current_acl_records=(acl,), current_chunk_records=(chunk,),
    )
    acl["document_id"] = "confluence:page:forged"
    assert request.current_acl_records[0]["document_id"] == summary.document_id


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_id": "chunk:bad"},
        {"content_hash": "bad"},
        {"part_index": 2, "part_total": 2},
        {"token_count": True},
        {"content_kind": object()},
    ],
)
def test_nested_entry_malformed_values_are_rejected(overrides: dict[str, object]) -> None:
    summary = _forged_summary(entries=(_forged_entry(**overrides),))
    with pytest.raises((TypeError, ValueError)):
        DeltaPropagationRequest(
            previous_dataset_version="base", current_dataset_version="next",
            previous_config_hash="a" * 64, current_config_hash="b" * 64,
            detected_at="2026-08-05T00:00:00Z", previous_summaries=(summary,), current_summaries=(),
        )
