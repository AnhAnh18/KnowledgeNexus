from __future__ import annotations

import json

import pytest

from knowledgenexus.foundation.domain.models import (
    ConfluenceAttachmentObservation,
    MediaMaterializationError,
    MediaMaterializationFailureCategory,
    MediaPolicyDecision,
    MediaMaterializationResult,
    MediaRelationIntent,
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.rules import MediaAssetRecordBuilder


def _observation(
    *,
    attachment_id: str = "2000",
    parent_page_id: str = "1000",
    filename: str = "diagram.drawio",
    mime_type: str | None = "application/xml",
    size_bytes: int | None = 10,
) -> ConfluenceAttachmentObservation:
    return ConfluenceAttachmentObservation(
        attachment_id=attachment_id,
        parent_page_id=parent_page_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        source_version="7",
        updated_at="2026-08-04T00:00:00Z",
        crawled_at="2026-08-04T00:00:01Z",
    )


def test_observation_canonicalizes_safe_metadata_and_rejects_paths() -> None:
    observation = _observation(filename="e\u0301.png", mime_type=" Image/PNG ")
    assert observation.filename == "é.png"
    assert observation.mime_type == "image/png"
    with pytest.raises((TypeError, ValueError)):
        _observation(filename="../secret.txt")
    with pytest.raises((TypeError, ValueError)):
        _observation(filename="bad\u2028name.txt")
    with pytest.raises((TypeError, ValueError)):
        _observation(size_bytes=True)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        _observation(attachment_id="bad-id")
    with pytest.raises((TypeError, ValueError)):
        _observation().__class__(
            attachment_id="2000",
            parent_page_id="1000",
            filename="a.bin",
            source_version="é" * 256,
            crawled_at="2026-08-04T00:00:00Z",
        )


@pytest.mark.parametrize(
    "policy,download_status,relevance",
    [
        ("metadata_only", "skipped", "unknown"),
        ("skip", "skipped", "low"),
        ("download_and_process", "not_attempted", "high"),
    ],
)
def test_builder_emits_schema_valid_metadata_first_record(policy, download_status, relevance) -> None:
    record = MediaAssetRecordBuilder.build(
        _observation(),
        MediaPolicyDecision("2000", policy),
    )
    assert record["media_id"] == "confluence:attachment:2000"
    assert record["parent_document_id"] == "confluence:page:1000"
    assert record["download_status"] == download_status
    assert record["processing_status"] == "not_processed"
    assert record["relevance"] == relevance
    for field in ("extracted_text", "summary", "confidence", "raw_uri", "content_hash"):
        assert record[field] is None
    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def test_batch_is_sorted_and_maps_media_intents_without_attachment_chunks() -> None:
    observations = (
        _observation(attachment_id="2001", filename="image.png", mime_type="image/png"),
        _observation(attachment_id="2000", filename="diagram.drawio"),
    )
    decisions = (
        MediaPolicyDecision("2001", "metadata_only"),
        MediaPolicyDecision("2000", "download_and_process"),
    )
    intents = (
        NormalizationReferenceIntent(1, "drawio", "deferred_mvp", "diagram.drawio", "diagram.drawio"),
        NormalizationReferenceIntent(2, "image_attachment", "deferred_mvp", "missing.png", "missing.png"),
        NormalizationReferenceIntent(3, "include_page", "unresolved_target", "unknown", "unknown"),
    )
    result = MediaAssetRecordBuilder.build_batch(
        observations,
        decisions,
        intents,
    )
    assert [record["media_id"] for record in result.assets] == [
        "confluence:attachment:2000",
        "confluence:attachment:2001",
    ]
    assert result.assets[0]["filename"] == "diagram.drawio"
    assert len(result.relation_intents) == 2
    assert result.relation_intents[0].target_media_id == "confluence:attachment:2000"
    assert result.relation_intents[1].target_media_id is None
    assert [item.ordinal for item in result.relation_intents] == [1, 2]


def test_batch_rejects_duplicate_or_ambiguous_inputs_atomically() -> None:
    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build_batch(
            (_observation(), _observation()),
            (MediaPolicyDecision("2000", "skip"),),
        )
    assert exc_info.value.category == MediaMaterializationFailureCategory.DUPLICATE_ID

    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build_batch(
            (_observation(),),
            (MediaPolicyDecision("2000", "skip"),),
            (
                NormalizationReferenceIntent(1, "drawio", "deferred_mvp", "diagram.drawio", "diagram.drawio"),
                NormalizationReferenceIntent(2, "drawio", "deferred_mvp", "diagram.drawio", "diagram.drawio"),
            ),
        )
    assert exc_info.value.category == MediaMaterializationFailureCategory.DUPLICATE_ID
    assert "diagram" not in str(exc_info.value)


def test_batch_rejects_forbidden_intent_and_policy_types_before_validator_access() -> None:
    class HostileValidator:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("SECRET VALIDATOR")

    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build_batch(
            object(),
            (),
            schema_validator=HostileValidator(),
        )
    assert exc_info.value.category == MediaMaterializationFailureCategory.INVALID_INPUT

    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build_batch(
            (_observation(),),
            (MediaPolicyDecision("2000", "skip"),),
            (NormalizationReferenceIntent(2, "drawio", "deferred_mvp", "diagram.drawio", "diagram.drawio"),),
            schema_validator=HostileValidator(),
        )
    assert exc_info.value.category == MediaMaterializationFailureCategory.INVALID_INTENT
    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build(
            _observation(),
            MediaPolicyDecision("2000", "skip"),
            schema_validator=HostileValidator(),
        )
    assert exc_info.value.category == MediaMaterializationFailureCategory.INVALID_INPUT


def test_builder_rejects_bypassed_typed_inputs_without_raw_attribute_errors() -> None:
    observation = object.__new__(ConfluenceAttachmentObservation)
    decision = object.__new__(MediaPolicyDecision)
    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build(observation, decision)
    assert exc_info.value.category == MediaMaterializationFailureCategory.INVALID_OBSERVATION
    assert "AttributeError" not in str(exc_info.value)

    valid_observation = _observation()
    valid_decision = MediaPolicyDecision("2000", "skip")
    intent = object.__new__(NormalizationReferenceIntent)
    with pytest.raises(MediaMaterializationError) as exc_info:
        MediaAssetRecordBuilder.build_batch(
            (valid_observation,),
            (valid_decision,),
            (intent,),
        )
    assert exc_info.value.category == MediaMaterializationFailureCategory.INVALID_INTENT


def test_materialization_result_rejects_bypassed_relation_intent() -> None:
    malformed = object.__new__(MediaRelationIntent)
    with pytest.raises((TypeError, ValueError)):
        MediaMaterializationResult(assets=(), relation_intents=(malformed,))


def test_materialization_result_rejects_forbidden_asset_state() -> None:
    record = MediaAssetRecordBuilder.build(
        _observation(),
        MediaPolicyDecision("2000", "skip"),
    )
    record["processing_status"] = "parsed"
    with pytest.raises((TypeError, ValueError)):
        MediaMaterializationResult(assets=(record,), relation_intents=())


def test_relation_intent_rejects_line_separators() -> None:
    with pytest.raises((TypeError, ValueError)):
        MediaRelationIntent(
            ordinal=1,
            source_document_id="confluence:page:1000",
            target_media_id=None,
            intent_kind="drawio",
            relation_type="embeds_media",
            resolution_status="unresolved_target",
            evidence="bad\u2029identity",
        )
