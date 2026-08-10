from __future__ import annotations

import hashlib

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaAttachmentPublicationOutcome,
    MediaAttachmentRawArtifact,
    MediaBodyMaterializationError,
    MediaBodyMaterializationFailureCategory,
    MediaBodyMaterializationResult,
    MediaBodyStoreBudget,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
    MediaPolicyDecision,
)
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.foundation.ports.confluence_attachment_body_fetch_port import (
    ConfluenceAttachmentBodyFetchError,
    ConfluenceAttachmentBodyFetchPort,
    ConfluenceAttachmentBodyTooLargeError,
)
from knowledgenexus.foundation.ports.confluence_raw_attachment_store_port import (
    ConfluenceRawAttachmentStoreError,
    ConfluenceRawAttachmentStoreFailureCategory,
    ConfluenceRawAttachmentStorePort,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


def _fail(category: MediaBodyMaterializationFailureCategory) -> None:
    raise MediaBodyMaterializationError(category) from None


class FetchAndStoreConfluenceAttachmentBody:
    """Fetch one selected attachment and publish immutable raw evidence."""

    def __init__(
        self,
        *,
        body_fetcher: ConfluenceAttachmentBodyFetchPort,
        raw_attachment_store: ConfluenceRawAttachmentStorePort,
        budget: MediaBodyStoreBudget,
        schema_validator: object | None = None,
    ) -> None:
        if type(budget) is not MediaBodyStoreBudget:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        try:
            validated_budget = MediaBodyStoreBudget(
                max_body_bytes=budget.max_body_bytes,
                max_total_bytes=budget.max_total_bytes,
                minimum_free_disk_reserve_bytes=budget.minimum_free_disk_reserve_bytes,
            )
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        try:
            fetch = getattr(body_fetcher, "fetch_attachment_body", None)
            resolve = getattr(raw_attachment_store, "resolve_attachment_path", None)
            publish = getattr(raw_attachment_store, "publish_attachment", None)
            read = getattr(raw_attachment_store, "read_attachment", None)
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        if not callable(fetch) or not callable(resolve) or not callable(publish) or not callable(read):
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        try:
            validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
            validate_record = getattr(validator, "validate_record", None)
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        if not callable(validate_record):
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        self._body_fetcher = body_fetcher
        self._raw_attachment_store = raw_attachment_store
        self._budget = validated_budget
        self._schema_validator = validator

    def execute(
        self,
        *,
        observation: object,
        decision: object,
    ) -> MediaBodyMaterializationResult:
        if type(observation) is not ConfluenceAttachmentObservation:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        if type(decision) is not MediaPolicyDecision:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_INPUT)
        observation = self._revalidate_observation(observation)
        decision = self._revalidate_decision(decision)
        if observation.attachment_id != decision.attachment_id:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_POLICY)
        if decision.policy != "download_and_process":
            _fail(MediaBodyMaterializationFailureCategory.INVALID_POLICY)
        if (
            observation.source_version is None
            or not observation.source_version.isascii()
            or not observation.source_version.isdecimal()
            or observation.source_version.startswith("0")
        ):
            _fail(MediaBodyMaterializationFailureCategory.INVALID_OBSERVATION)
        if observation.size_bytes is not None and observation.size_bytes > self._budget.max_body_bytes:
            _fail(MediaBodyMaterializationFailureCategory.RESPONSE_SIZE_LIMIT)

        try:
            response = self._body_fetcher.fetch_attachment_body(
                attachment_id=observation.attachment_id,
                parent_page_id=observation.parent_page_id,
                filename=observation.filename,
                source_version=observation.source_version,
                max_bytes=self._budget.max_body_bytes,
            )
        except ConfluenceAttachmentBodyTooLargeError:
            _fail(MediaBodyMaterializationFailureCategory.RESPONSE_SIZE_LIMIT)
        except ConfluenceAttachmentBodyFetchError:
            _fail(MediaBodyMaterializationFailureCategory.FETCH)
        except (TypeError, ValueError, OSError):
            _fail(MediaBodyMaterializationFailureCategory.FETCH)
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.FETCH)
        if type(response) is not RawHttpObservation:
            _fail(MediaBodyMaterializationFailureCategory.FETCH)
        try:
            status_code = response.status_code
            response_body = response.body
            if type(status_code) is not int or type(response_body) is not bytes:
                _fail(MediaBodyMaterializationFailureCategory.FETCH)
            response = RawHttpObservation(status_code=status_code, body=response_body)
        except MediaBodyMaterializationError:
            raise
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.FETCH)
        if response.status_code != 200:
            _fail(MediaBodyMaterializationFailureCategory.HTTP)
        body = response.body
        if len(body) > self._budget.max_body_bytes:
            _fail(MediaBodyMaterializationFailureCategory.RESPONSE_SIZE_LIMIT)
        if observation.size_bytes is not None and observation.size_bytes != len(body):
            _fail(MediaBodyMaterializationFailureCategory.METADATA_MISMATCH)

        envelope = MediaAttachmentBodyEnvelope(
            format_version="1",
            evidence_kind="confluence_attachment_body",
            attachment_id=observation.attachment_id,
            parent_page_id=observation.parent_page_id,
            filename=observation.filename,
            source_version=observation.source_version,
            http_status=200,
            body_encoding="base64",
            body_bytes=body,
        )
        content_hash = hashlib.sha256(body).hexdigest()
        try:
            predicted_path = self._raw_attachment_store.resolve_attachment_path(
                attachment_id=observation.attachment_id,
                content_hash=content_hash,
            )
        except ConfluenceRawAttachmentStoreError as exc:
            _fail(
                self._store_category(
                    exc, fallback=MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID
                )
            )
        except (TypeError, ValueError, OSError):
            _fail(MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID)
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID)
        try:
            predicted_artifact = MediaAttachmentRawArtifact(
                path=predicted_path,
                attachment_id=observation.attachment_id,
                body_sha256=content_hash,
                byte_count=len(body),
                raw_uri=(
                    f"raw://confluence/attachments/{observation.attachment_id}/{content_hash}"
                ),
                outcome=MediaAttachmentPublicationOutcome.PUBLISHED,
            )
        except (TypeError, ValueError):
            _fail(MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID)
        asset = self._asset(observation=observation, artifact=predicted_artifact)
        try:
            self._schema_validator.validate_record("MediaAsset", asset)
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.SCHEMA_INVALID)
        try:
            artifact = self._raw_attachment_store.publish_attachment(envelope=envelope)
        except ConfluenceRawAttachmentStoreError as exc:
            _fail(
                self._store_category(
                    exc, fallback=MediaBodyMaterializationFailureCategory.RAW_PUBLICATION_FAILURE
                )
            )
        except (TypeError, ValueError, OSError):
            _fail(MediaBodyMaterializationFailureCategory.RAW_PUBLICATION_FAILURE)
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.RAW_PUBLICATION_FAILURE)
        artifact = self._revalidate_artifact(artifact)
        if (
            artifact.attachment_id != predicted_artifact.attachment_id
            or artifact.body_sha256 != predicted_artifact.body_sha256
            or artifact.byte_count != predicted_artifact.byte_count
            or artifact.raw_uri != predicted_artifact.raw_uri
            or artifact.path != predicted_artifact.path
        ):
            _fail(MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID)
        try:
            return MediaBodyMaterializationResult(
                asset=self._asset(observation=observation, artifact=artifact),
                artifact=artifact,
            )
        except (TypeError, ValueError):
            _fail(MediaBodyMaterializationFailureCategory.INTERNAL_FAILURE)

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
            _fail(MediaBodyMaterializationFailureCategory.INVALID_OBSERVATION)

    @staticmethod
    def _revalidate_decision(value: MediaPolicyDecision) -> MediaPolicyDecision:
        try:
            return MediaPolicyDecision(
                attachment_id=value.attachment_id,
                policy=value.policy,
            )
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.INVALID_POLICY)

    @staticmethod
    def _revalidate_artifact(value: object) -> MediaAttachmentRawArtifact:
        if type(value) is not MediaAttachmentRawArtifact:
            _fail(MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID)
        try:
            return MediaAttachmentRawArtifact(
                path=value.path,
                attachment_id=value.attachment_id,
                body_sha256=value.body_sha256,
                byte_count=value.byte_count,
                raw_uri=value.raw_uri,
                outcome=value.outcome,
            )
        except Exception:
            _fail(MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID)

    @staticmethod
    def _asset(
        *,
        observation: ConfluenceAttachmentObservation,
        artifact: MediaAttachmentRawArtifact,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "media_id": DocumentIdGenerator.confluence_attachment_id(observation.attachment_id),
            "parent_document_id": DocumentIdGenerator.confluence_page_id(observation.parent_page_id),
            "source_system": "confluence",
            "filename": observation.filename,
            "mime_type": observation.mime_type,
            "size_bytes": observation.size_bytes,
            "download_status": "downloaded",
            "processing_status": "not_processed",
            "relevance": "high",
            "extracted_text": None,
            "summary": None,
            "confidence": None,
            "raw_uri": artifact.raw_uri,
            "content_hash": artifact.body_sha256,
            "source_version": observation.source_version,
            "updated_at": observation.updated_at,
            "crawled_at": observation.crawled_at,
        }

    @staticmethod
    def _store_category(
        error: object,
        *,
        fallback: MediaBodyMaterializationFailureCategory,
    ) -> MediaBodyMaterializationFailureCategory:
        try:
            category = error.category
        except Exception:
            return fallback
        if not isinstance(category, ConfluenceRawAttachmentStoreFailureCategory):
            return fallback
        if category is ConfluenceRawAttachmentStoreFailureCategory.RAW_REPLAY_CONFLICT:
            return MediaBodyMaterializationFailureCategory.RAW_REPLAY_CONFLICT
        if category is ConfluenceRawAttachmentStoreFailureCategory.RAW_ARTIFACT_INVALID:
            return MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID
        if category is ConfluenceRawAttachmentStoreFailureCategory.BUDGET_EXCEEDED:
            return MediaBodyMaterializationFailureCategory.BUDGET_EXCEEDED
        return MediaBodyMaterializationFailureCategory.RAW_PUBLICATION_FAILURE

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


__all__ = ["FetchAndStoreConfluenceAttachmentBody"]
