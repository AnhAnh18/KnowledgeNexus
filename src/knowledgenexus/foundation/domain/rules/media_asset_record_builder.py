from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_page_content import (
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
    MediaMaterializationError,
    MediaMaterializationFailureCategory,
    MediaMaterializationResult,
    MediaPolicyDecision,
    MediaRelationIntent,
)
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


class _SchemaValidatorPort(Protocol):
    def validate_record(self, schema_name: str, record: dict[str, object]) -> None: ...


def _fail(category: str) -> None:
    raise MediaMaterializationError(category)


class MediaAssetRecordBuilder:
    """Build schema-valid metadata-first MediaAsset records without I/O."""

    @classmethod
    def build(
        cls,
        observation: object,
        decision: object,
        *,
        schema_validator: object | None = None,
    ) -> dict[str, object]:
        if type(observation) is not ConfluenceAttachmentObservation or type(decision) is not MediaPolicyDecision:
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        observation = MediaAssetRecordBuilder._revalidate_observation(observation)
        decision = MediaAssetRecordBuilder._revalidate_decision(decision)
        if observation.attachment_id != decision.attachment_id:
            _fail(MediaMaterializationFailureCategory.CROSS_PAGE)
        validator = cls._validator(schema_validator)
        record = cls._record(observation, decision)
        cls._validate_record(record, validator)
        return dict(record)

    @classmethod
    def build_batch(
        cls,
        observations: object,
        decisions: object,
        reference_intents: object = (),
        *,
        schema_validator: object | None = None,
    ) -> MediaMaterializationResult:
        if type(observations) is not tuple or type(decisions) is not tuple or type(reference_intents) is not tuple:
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        if any(type(item) is not ConfluenceAttachmentObservation for item in observations):
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        if any(type(item) is not MediaPolicyDecision for item in decisions):
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        if any(type(item) is not NormalizationReferenceIntent for item in reference_intents):
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        try:
            observations = tuple(cls._revalidate_observation(item) for item in observations)
            decisions = tuple(cls._revalidate_decision(item) for item in decisions)
            reference_intents = tuple(cls._revalidate_intent(item) for item in reference_intents)
        except (TypeError, ValueError, AttributeError):
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        cls._validate_intents(reference_intents)
        observation_by_id: dict[str, ConfluenceAttachmentObservation] = {}
        for observation in observations:
            if observation.attachment_id in observation_by_id:
                _fail(MediaMaterializationFailureCategory.DUPLICATE_ID)
            observation_by_id[observation.attachment_id] = observation
        decision_by_id: dict[str, MediaPolicyDecision] = {}
        for decision in decisions:
            if decision.attachment_id in decision_by_id:
                _fail(MediaMaterializationFailureCategory.DUPLICATE_ID)
            decision_by_id[decision.attachment_id] = decision
        if set(observation_by_id) != set(decision_by_id):
            _fail(MediaMaterializationFailureCategory.CROSS_PAGE)
        parent_pages = {observation.parent_page_id for observation in observations}
        if len(parent_pages) > 1 and reference_intents:
            _fail(MediaMaterializationFailureCategory.CROSS_PAGE)
        relation_intents = cls._map_intents(
            reference_intents=reference_intents,
            observations=tuple(observation_by_id.values()),
        )
        validator = cls._validator(schema_validator)
        records = tuple(
            cls._record(observation_by_id[attachment_id], decision_by_id[attachment_id])
            for attachment_id in sorted(observation_by_id)
        )
        for record in records:
            cls._validate_record(record, validator)
        try:
            return MediaMaterializationResult(
                assets=records,
                relation_intents=relation_intents,
            )
        except (TypeError, ValueError):
            _fail(MediaMaterializationFailureCategory.INTERNAL_FAILURE)

    @staticmethod
    def _record(
        observation: ConfluenceAttachmentObservation,
        decision: MediaPolicyDecision,
    ) -> dict[str, object]:
        if decision.policy == "metadata_only":
            download_status, relevance = "skipped", "unknown"
        elif decision.policy == "skip":
            download_status, relevance = "skipped", "low"
        elif decision.policy == "download_and_process":
            download_status, relevance = "not_attempted", "high"
        else:  # pragma: no cover - MediaPolicyDecision closes this union
            _fail(MediaMaterializationFailureCategory.INVALID_POLICY)
        return {
            "schema_version": SCHEMA_VERSION,
            "media_id": DocumentIdGenerator.confluence_attachment_id(observation.attachment_id),
            "parent_document_id": DocumentIdGenerator.confluence_page_id(observation.parent_page_id),
            "source_system": "confluence",
            "filename": observation.filename,
            "mime_type": observation.mime_type,
            "size_bytes": observation.size_bytes,
            "download_status": download_status,
            "processing_status": "not_processed",
            "relevance": relevance,
            "extracted_text": None,
            "summary": None,
            "confidence": None,
            "raw_uri": None,
            "content_hash": None,
            "source_version": observation.source_version,
            "updated_at": observation.updated_at,
            "crawled_at": observation.crawled_at,
        }

    @staticmethod
    def _revalidate_observation(value: ConfluenceAttachmentObservation) -> ConfluenceAttachmentObservation:
        try:
            return ConfluenceAttachmentObservation(
                attachment_id=value.attachment_id,
                parent_page_id=value.parent_page_id,
                filename=value.filename,
                mime_type=value.mime_type,
                size_bytes=value.size_bytes,
                source_version=value.source_version,
                updated_at=value.updated_at,
                crawled_at=value.crawled_at,
            )
        except Exception:
            _fail(MediaMaterializationFailureCategory.INVALID_OBSERVATION)

    @staticmethod
    def _revalidate_decision(value: MediaPolicyDecision) -> MediaPolicyDecision:
        try:
            return MediaPolicyDecision(
                attachment_id=value.attachment_id,
                policy=value.policy,
            )
        except Exception:
            _fail(MediaMaterializationFailureCategory.INVALID_POLICY)

    @staticmethod
    def _revalidate_intent(value: NormalizationReferenceIntent) -> NormalizationReferenceIntent:
        try:
            return NormalizationReferenceIntent(
                ordinal=value.ordinal,
                kind=value.kind,
                status=value.status,
                target_identity=value.target_identity,
                placeholder_identity=value.placeholder_identity,
            )
        except Exception:
            _fail(MediaMaterializationFailureCategory.INVALID_INTENT)

    @staticmethod
    def _map_intents(
        *,
        reference_intents: tuple[NormalizationReferenceIntent, ...],
        observations: tuple[ConfluenceAttachmentObservation, ...],
    ) -> tuple[MediaRelationIntent, ...]:
        if not reference_intents:
            return ()
        parent_pages = {observation.parent_page_id for observation in observations}
        if len(parent_pages) != 1:
            _fail(MediaMaterializationFailureCategory.CROSS_PAGE)
        parent_page_id = next(iter(parent_pages))
        source_document_id = DocumentIdGenerator.confluence_page_id(parent_page_id)
        filenames: dict[str, str] = {}
        for observation in observations:
            if observation.filename in filenames:
                filenames[observation.filename] = ""
            else:
                filenames[observation.filename] = observation.attachment_id
        seen: set[tuple[str, str]] = set()
        output: list[MediaRelationIntent] = []
        for intent in reference_intents:
            key = (intent.kind, intent.target_identity)
            if key in seen:
                _fail(MediaMaterializationFailureCategory.DUPLICATE_ID)
            seen.add(key)
            if intent.kind == "include_page":
                continue
            if intent.kind not in {"drawio", "image_attachment"}:
                _fail(MediaMaterializationFailureCategory.INVALID_INTENT)
            attachment_id = filenames.get(intent.target_identity)
            target_media_id = None
            if attachment_id:
                target_media_id = DocumentIdGenerator.confluence_attachment_id(attachment_id)
            output.append(
                MediaRelationIntent(
                    ordinal=len(output) + 1,
                    source_document_id=source_document_id,
                    target_media_id=target_media_id,
                    intent_kind=intent.kind,
                    relation_type="embeds_media",
                    resolution_status="unresolved_target",
                    evidence=intent.target_identity,
                )
            )
        return tuple(output)

    @staticmethod
    def _validate_intents(reference_intents: tuple[NormalizationReferenceIntent, ...]) -> None:
        ordinals = tuple(intent.ordinal for intent in reference_intents)
        if ordinals != tuple(range(1, len(ordinals) + 1)):
            _fail(MediaMaterializationFailureCategory.INVALID_INTENT)
        seen: set[tuple[str, str]] = set()
        for intent in reference_intents:
            key = (intent.kind, intent.target_identity)
            if key in seen:
                _fail(MediaMaterializationFailureCategory.DUPLICATE_ID)
            seen.add(key)

    @staticmethod
    def _validator(schema_validator: object | None) -> _SchemaValidatorPort:
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
            validate_record = getattr(validator, "validate_record", None)
        except Exception:
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        if not callable(validate_record):
            _fail(MediaMaterializationFailureCategory.INVALID_INPUT)
        return validator

    @staticmethod
    def _validate_record(record: dict[str, object], validator: _SchemaValidatorPort) -> None:
        try:
            validator.validate_record("MediaAsset", record)
        except Exception:
            _fail(MediaMaterializationFailureCategory.SCHEMA_INVALID)


__all__ = ["MediaAssetRecordBuilder"]
