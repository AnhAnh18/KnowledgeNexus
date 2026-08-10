from __future__ import annotations

import hashlib

import pytest

from knowledgenexus.foundation.application.use_cases import PropagateDelta
from knowledgenexus.foundation.domain.models import (
    ACTIVE_CHUNKER_VERSION,
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ChunkStabilityEntry,
    DeltaInventoryEntry,
    DeltaInventoryState,
    DeltaPropagationFailureCategory,
    DeltaPropagationRequest,
    DeltaPropagationStatus,
    DocumentChunkSetSummary,
    TombstoneEntityType,
    TombstoneTarget,
)


class Validator:
    def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
        assert schema_name == "TombstoneRecord"


def _entry(chunk_id: str, content_hash: str = "b" * 64) -> ChunkStabilityEntry:
    return ChunkStabilityEntry(chunk_id, content_hash, "prose", 1)


def _summary(document_id: str, content_hash: str = "a" * 64, entries=()) -> DocumentChunkSetSummary:
    entries = tuple(entries)
    return DocumentChunkSetSummary(
        format_version="1",
        document_id=document_id,
        document_content_hash=content_hash,
        chunker_version=ACTIVE_CHUNKER_VERSION,
        profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        entries=entries,
        chunk_count=len(entries),
        content_kind_counts=(("prose", len(entries)),) if entries else (),
    )


def _request(previous=(), current=(), inventory=(), *, previous_config="a" * 64, current_config="a" * 64, previous_dependents=()):
    return DeltaPropagationRequest(
        previous_dataset_version="base",
        current_dataset_version="next",
        previous_config_hash=previous_config,
        current_config_hash=current_config,
        detected_at="2026-08-05T00:00:00Z",
        previous_summaries=tuple(previous),
        current_summaries=tuple(current),
        inventory=tuple(inventory),
        previous_dependents=tuple(previous_dependents),
    )


def _forged_request(*, previous=(), current=()) -> DeltaPropagationRequest:
    request = object.__new__(DeltaPropagationRequest)
    object.__setattr__(request, "previous_dataset_version", "base")
    object.__setattr__(request, "current_dataset_version", "next")
    object.__setattr__(request, "previous_config_hash", "a" * 64)
    object.__setattr__(request, "current_config_hash", "a" * 64)
    object.__setattr__(request, "detected_at", "2026-08-05T00:00:00.000000Z")
    object.__setattr__(request, "previous_summaries", tuple(previous))
    object.__setattr__(request, "current_summaries", tuple(current))
    object.__setattr__(request, "inventory", ())
    return request


_SUMMARY_FIELDS = (
    "format_version", "document_id", "document_content_hash", "chunker_version",
    "profile_identity", "entries", "chunk_count", "content_kind_counts",
)
_ENTRY_FIELDS = ("chunk_id", "content_hash", "content_kind", "token_count", "part_index", "part_total")


def _forged_entry(*, missing: str | None = None, extra: bool = False, **overrides) -> ChunkStabilityEntry:
    valid = _entry("chunk:confluence:0123456789abcdef")
    forged = object.__new__(ChunkStabilityEntry)
    for field in _ENTRY_FIELDS:
        if field != missing:
            object.__setattr__(forged, field, overrides.get(field, getattr(valid, field)))
    if extra:
        object.__setattr__(forged, "extra", 1)
    return forged


def _forged_summary(*, missing: str | None = None, extra: bool = False, entries=()) -> DocumentChunkSetSummary:
    valid = _summary("confluence:page:1")
    forged = object.__new__(DocumentChunkSetSummary)
    for field in _SUMMARY_FIELDS:
        value = tuple(entries) if field == "entries" else getattr(valid, field)
        if field != missing:
            object.__setattr__(forged, field, value)
    if extra:
        object.__setattr__(forged, "extra", 1)
    return forged


def test_empty_new_and_unchanged_delta_is_success_and_deterministic() -> None:
    summary = _summary("confluence:page:1")
    use_case = PropagateDelta(schema_validator=Validator())
    result = use_case.execute(_request(current=(summary,)))
    assert result.status is DeltaPropagationStatus.SUCCESS
    assert result.count == 0
    assert result.metrics.new_document_count == 1
    assert result.digest == hashlib.sha256(result.to_bytes()).hexdigest()

    unchanged = use_case.execute(_request(previous=(summary,), current=(summary,)))
    assert unchanged.count == 0
    assert unchanged.metrics.unchanged_document_count == 1


def test_changed_chunk_emits_only_removed_or_changed_previous_chunks() -> None:
    old = _summary(
        "confluence:page:1",
        entries=(
            _entry("chunk:confluence:0123456789abcdef", "b" * 64),
            _entry("chunk:confluence:fedcba9876543210", "c" * 64),
        ),
        content_hash="a" * 64,
    )
    new = _summary(
        "confluence:page:1",
        entries=(_entry("chunk:confluence:0123456789abcdef", "d" * 64),),
        content_hash="e" * 64,
    )
    result = PropagateDelta(schema_validator=Validator()).execute(_request(previous=(old,), current=(new,)))
    assert result.status is DeltaPropagationStatus.SUCCESS
    assert result.metrics.changed_document_count == 1
    assert result.metrics.chunk_tombstone_count == 2
    assert all(record["entity_type"] == "chunk" for record in result.records)


@pytest.mark.parametrize("state", [
    DeltaInventoryState.SOURCE_DELETED,
    DeltaInventoryState.ACCESS_REVOKED,
    DeltaInventoryState.MOVED_OUT_OF_SCOPE,
    DeltaInventoryState.CONFIG_INVALIDATED,
])
def test_inventory_removal_emits_document_cascade(state: DeltaInventoryState) -> None:
    old = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    inventory = (DeltaInventoryEntry("confluence:page:1", state, "v7"),)
    result = PropagateDelta(schema_validator=Validator()).execute(_request(previous=(old,), inventory=inventory))
    assert result.status is DeltaPropagationStatus.SUCCESS
    assert result.metrics.removed_document_count == 1
    assert result.metrics.document_tombstone_count == 1
    assert result.metrics.chunk_tombstone_count == 1
    assert result.records[0]["entity_type"] == "document"
    assert result.records[0]["reason"] == state.value
    assert result.records[0]["source_version_last_seen"] == "v7"


def test_config_change_invalidates_present_previous_documents() -> None:
    old = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    current = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    result = PropagateDelta(schema_validator=Validator()).execute(
        _request(previous=(old,), current=(current,), previous_config="a" * 64, current_config="b" * 64)
    )
    assert result.metrics.changed_document_count == 1
    assert result.records[0]["reason"] == "config_invalidated"


def test_removed_document_cascades_prior_media_relation_acl_and_symbol_targets() -> None:
    old = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    dependents = (
        TombstoneTarget(TombstoneEntityType.MEDIA, "confluence:attachment:att-1"),
        TombstoneTarget(TombstoneEntityType.RELATION, "rel:0123456789abcdef"),
        TombstoneTarget(TombstoneEntityType.ACL, "acl:confluence:page:1"),
        TombstoneTarget(TombstoneEntityType.SYMBOL, "symbol:git:file:1"),
    )
    request = _request(previous=(old,), previous_dependents=((old.document_id, dependents),))
    result = PropagateDelta(schema_validator=Validator()).execute(request)
    assert result.status is DeltaPropagationStatus.SUCCESS
    assert {record["entity_type"] for record in result.records} == {"document", "chunk", "media", "relation", "acl", "symbol"}
    assert result.metrics.media_tombstone_count == 1
    assert result.metrics.relation_tombstone_count == 1
    assert result.metrics.acl_tombstone_count == 1
    assert result.metrics.symbol_tombstone_count == 1


def test_dependents_reject_document_root_and_duplicate_targets() -> None:
    old = _summary("confluence:page:1")
    with pytest.raises(ValueError):
        _request(previous=(old,), previous_dependents=((old.document_id, (TombstoneTarget(TombstoneEntityType.DOCUMENT, old.document_id),)),))


def test_conflicting_inventory_is_atomic() -> None:
    old = _summary("confluence:page:1")
    request = object.__new__(DeltaPropagationRequest)
    object.__setattr__(request, "previous_dataset_version", "base")
    object.__setattr__(request, "current_dataset_version", "next")
    object.__setattr__(request, "previous_config_hash", "a" * 64)
    object.__setattr__(request, "current_config_hash", "a" * 64)
    object.__setattr__(request, "detected_at", "2026-08-05T00:00:00.000000Z")
    object.__setattr__(request, "previous_summaries", (old,))
    object.__setattr__(request, "current_summaries", ())
    object.__setattr__(request, "inventory", (DeltaInventoryEntry("confluence:page:1", DeltaInventoryState.PRESENT),))
    result = PropagateDelta(schema_validator=Validator()).execute(request)
    assert result.status is DeltaPropagationStatus.FAILED
    assert result.error_category is DeltaPropagationFailureCategory.INVENTORY_CONFLICT
    assert result.records == () and result.count == 0 and result.metrics is None


def test_invalid_summary_is_sanitized() -> None:
    request = object.__new__(DeltaPropagationRequest)
    object.__setattr__(request, "previous_dataset_version", "base")
    object.__setattr__(request, "current_dataset_version", "next")
    object.__setattr__(request, "previous_config_hash", "a" * 64)
    object.__setattr__(request, "current_config_hash", "a" * 64)
    object.__setattr__(request, "detected_at", "2026-08-05T00:00:00.000000Z")
    object.__setattr__(request, "previous_summaries", (object(),))
    object.__setattr__(request, "current_summaries", ())
    object.__setattr__(request, "inventory", ())
    result = PropagateDelta(schema_validator=Validator()).execute(request)
    assert result.error_category is DeltaPropagationFailureCategory.SUMMARY_INVALID


def test_duplicate_inventory_conflict_is_atomic() -> None:
    old = _summary("confluence:page:1")
    inventory = (
        DeltaInventoryEntry("confluence:page:1", DeltaInventoryState.SOURCE_DELETED),
        DeltaInventoryEntry("confluence:page:1", DeltaInventoryState.ACCESS_REVOKED),
    )
    with pytest.raises(ValueError):
        _request(previous=(old,), inventory=inventory)


def test_changed_document_without_affected_old_chunks_has_no_records() -> None:
    old = _summary("confluence:page:1", content_hash="a" * 64)
    new = _summary("confluence:page:1", content_hash="c" * 64)
    result = PropagateDelta(schema_validator=Validator()).execute(_request(previous=(old,), current=(new,)))
    assert result.status is DeltaPropagationStatus.SUCCESS
    assert result.count == 0
    assert result.metrics.changed_document_count == 1
    assert result.document_outcomes == (("confluence:page:1", "changed"),)


def test_validator_failure_is_sanitized_and_atomic() -> None:
    class RejectingValidator:
        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            record.pop("entity_id")

    old = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    result = PropagateDelta(schema_validator=RejectingValidator()).execute(_request(previous=(old,)))
    assert result.status is DeltaPropagationStatus.FAILED
    assert result.error_category is DeltaPropagationFailureCategory.TOMBSTONE_FAILURE
    assert result.records == () and result.count == 0 and result.metrics is None


def test_forged_nested_summary_is_summary_invalid() -> None:
    old = _summary("confluence:page:1", entries=(_entry("chunk:confluence:0123456789abcdef"),))
    object.__setattr__(old.entries[0], "content_hash", "bad")
    request = object.__new__(DeltaPropagationRequest)
    object.__setattr__(request, "previous_dataset_version", "base")
    object.__setattr__(request, "current_dataset_version", "next")
    object.__setattr__(request, "previous_config_hash", "a" * 64)
    object.__setattr__(request, "current_config_hash", "a" * 64)
    object.__setattr__(request, "detected_at", "2026-08-05T00:00:00.000000Z")
    object.__setattr__(request, "previous_summaries", (old,))
    object.__setattr__(request, "current_summaries", ())
    object.__setattr__(request, "inventory", ())
    result = PropagateDelta(schema_validator=Validator()).execute(request)
    assert result.status is DeltaPropagationStatus.FAILED
    assert result.error_category is DeltaPropagationFailureCategory.SUMMARY_INVALID
    assert result.records == () and result.count == 0


@pytest.mark.parametrize("position", ("previous", "current"))
def test_malformed_summary_fails_before_validator_or_projector(position: str) -> None:
    summary = object.__new__(DocumentChunkSetSummary)
    valid = _summary("confluence:page:1")
    for field in ("format_version", "document_id", "document_content_hash", "chunker_version", "profile_identity", "entries", "chunk_count", "content_kind_counts"):
        object.__setattr__(summary, field, getattr(valid, field))
    object.__setattr__(summary, "extra", 1)
    request = _forged_request(previous=(summary,) if position == "previous" else (), current=(summary,) if position == "current" else ())

    class CountingValidator(Validator):
        def __init__(self) -> None:
            self.calls = 0

        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            self.calls += 1

    class CountingProjector:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: object) -> object:
            self.calls += 1
            raise AssertionError("projector must not run")

    validator = CountingValidator()
    use_case = PropagateDelta(schema_validator=validator)
    projector = CountingProjector()
    use_case._projector = projector
    result = use_case.execute(request)
    assert result.status is DeltaPropagationStatus.FAILED
    assert result.error_category is DeltaPropagationFailureCategory.SUMMARY_INVALID
    assert result.records == () and result.count == 0 and result.metrics is None
    assert validator.calls == 0 and projector.calls == 0


def _malformed_summary_cases() -> list[tuple[str, DocumentChunkSetSummary]]:
    cases = [(f"outer-missing-{field}", _forged_summary(missing=field)) for field in _SUMMARY_FIELDS]
    cases.append(("outer-extra", _forged_summary(extra=True)))
    cases.extend(
        (f"nested-missing-{field}", _forged_summary(entries=(_forged_entry(missing=field),)))
        for field in _ENTRY_FIELDS
    )
    cases.append(("nested-extra", _forged_summary(entries=(_forged_entry(extra=True),))))
    cases.extend(
        [
            ("nested-bad-id", _forged_summary(entries=(_forged_entry(chunk_id="chunk:bad"),))),
            ("nested-bad-hash", _forged_summary(entries=(_forged_entry(content_hash="bad"),))),
            ("nested-bad-parts", _forged_summary(entries=(_forged_entry(part_index=2, part_total=2),))),
            ("nested-bad-token-type", _forged_summary(entries=(_forged_entry(token_count=True),))),
            ("nested-bad-kind-type", _forged_summary(entries=(_forged_entry(content_kind=object()),))),
            ("nested-wrong-runtime-type", _forged_summary(entries=(object(),))),
        ]
    )
    return cases


@pytest.mark.parametrize("position", ("previous", "current"))
@pytest.mark.parametrize(
    "case_name,summary",
    _malformed_summary_cases(),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_every_malformed_summary_fails_at_execute_boundary(
    position: str, case_name: str, summary: DocumentChunkSetSummary,
) -> None:
    request = _forged_request(
        previous=(summary,) if position == "previous" else (),
        current=(summary,) if position == "current" else (),
    )

    class CountingValidator(Validator):
        def __init__(self) -> None:
            self.calls = 0

        def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
            self.calls += 1

    class CountingProjector:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: object) -> object:
            self.calls += 1
            raise AssertionError(f"projector must not run for {case_name}")

    validator = CountingValidator()
    use_case = PropagateDelta(schema_validator=validator)
    projector = CountingProjector()
    use_case._projector = projector
    result = use_case.execute(request)

    assert result.status is DeltaPropagationStatus.FAILED
    assert result.error_category is DeltaPropagationFailureCategory.SUMMARY_INVALID
    assert result.records == () and result.count == 0 and result.metrics is None
    assert validator.calls == 0 and projector.calls == 0
