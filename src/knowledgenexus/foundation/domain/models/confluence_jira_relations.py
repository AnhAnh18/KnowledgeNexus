from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConfluenceJiraRelationFailureCategory(StrEnum):
    """Sanitized M6E failures safe for operator output."""

    INVALID_NORMALIZED_BODY = "invalid_normalized_body"
    NORMALIZED_BODY_CONTENT_HASH_MISMATCH = (
        "normalized_body_content_hash_mismatch"
    )
    INVALID_CREATED_AT = "invalid_created_at"
    CANONICAL_DOCUMENT_INVALID = "canonical_document_invalid"
    CHUNK_RECORD_INVALID = "chunk_record_invalid"
    CANONICAL_CHUNK_IDENTITY_MISMATCH = "canonical_chunk_identity_mismatch"
    RELATION_STAGE_INPUT_NOT_PRISTINE = "relation_stage_input_not_pristine"
    RELATION_ID_COLLISION = "relation_id_collision"
    RELATION_RECORD_VALIDATION_FAILED = "relation_record_validation_failed"
    ENRICHED_DOCUMENT_VALIDATION_FAILED = (
        "enriched_document_validation_failed"
    )
    ENRICHED_CHUNK_VALIDATION_FAILED = "enriched_chunk_validation_failed"
    RELATION_CROSS_REFERENCE_INVALID = "relation_cross_reference_invalid"
    RELATION_EXTRACTION_FAILED = "relation_extraction_failed"


class ConfluenceJiraRelationError(Exception):
    """A relation-stage failure whose message contains only a stable category."""

    def __init__(self, category: ConfluenceJiraRelationFailureCategory) -> None:
        if not isinstance(category, ConfluenceJiraRelationFailureCategory):
            raise TypeError(
                "category expects ConfluenceJiraRelationFailureCategory"
            )
        self.category = category
        super().__init__(category.value)


@dataclass(frozen=True, repr=False)
class JiraRelationQualityObservation:
    """First-occurrence-ordered broad candidates retained for later reporting."""

    unique_key_like_candidates: tuple[str, ...]
    allowlisted_keys: tuple[str, ...]
    outside_allowlist_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "unique_key_like_candidates",
            "allowlisted_keys",
            "outside_allowlist_keys",
        ):
            value = getattr(self, field_name)
            if isinstance(value, (str, bytes)):
                raise TypeError(f"{field_name} expects a collection")
            copied = tuple(value)
            if not all(isinstance(entry, str) for entry in copied):
                raise TypeError(f"{field_name} expects string entries")
            object.__setattr__(self, field_name, copied)


@dataclass(frozen=True, repr=False)
class ConfluenceJiraRelationResult:
    """Frozen ownership-isolated schema-shaped M6E output."""

    enriched_canonical_document: dict[str, object]
    enriched_chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    quality_observation: JiraRelationQualityObservation
    metrics: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.enriched_canonical_document, dict):
            raise TypeError("enriched_canonical_document expects dict")
        if isinstance(self.enriched_chunks, (str, bytes)):
            raise TypeError("enriched_chunks expects a collection")
        if isinstance(self.relations, (str, bytes)):
            raise TypeError("relations expects a collection")
        chunks = tuple(self.enriched_chunks)
        relations = tuple(self.relations)
        if not all(isinstance(record, dict) for record in chunks):
            raise TypeError("enriched_chunks expects dict entries")
        if not all(isinstance(record, dict) for record in relations):
            raise TypeError("relations expects dict entries")
        if not isinstance(
            self.quality_observation, JiraRelationQualityObservation
        ):
            raise TypeError(
                "quality_observation expects JiraRelationQualityObservation"
            )
        if not isinstance(self.metrics, dict):
            raise TypeError("metrics expects dict")

        object.__setattr__(
            self,
            "enriched_canonical_document",
            _copy_json_object(self.enriched_canonical_document),
        )
        object.__setattr__(
            self,
            "enriched_chunks",
            tuple(_copy_json_object(record) for record in chunks),
        )
        object.__setattr__(
            self,
            "relations",
            tuple(_copy_json_object(record) for record in relations),
        )
        observation = self.quality_observation
        object.__setattr__(
            self,
            "quality_observation",
            JiraRelationQualityObservation(
                unique_key_like_candidates=observation.unique_key_like_candidates,
                allowlisted_keys=observation.allowlisted_keys,
                outside_allowlist_keys=observation.outside_allowlist_keys,
            ),
        )
        object.__setattr__(self, "metrics", _copy_json_object(self.metrics))


def copy_json_object(value: dict[str, object]) -> dict[str, object]:
    """Return a recursive ownership-isolated copy of one JSON object."""

    return _copy_json_object(value)


def _copy_json_object(value: dict[str, object]) -> dict[str, object]:
    copied: dict[str, object] = {}
    for key, entry in value.items():
        if not isinstance(key, str):
            raise TypeError("JSON object keys must be strings")
        copied[key] = _copy_json_value(entry)
    return copied


def _copy_json_value(value: object) -> object:
    if isinstance(value, dict):
        return _copy_json_object(value)
    if isinstance(value, list):
        return [_copy_json_value(entry) for entry in value]
    if isinstance(value, tuple):
        return tuple(_copy_json_value(entry) for entry in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("value must be JSON-compatible")
