from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.fetch_and_store_confluence_attachment_body import (
    FetchAndStoreConfluenceAttachmentBody,
)
from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    RawHttpObservation,
)
from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
    MediaAttachmentPublicationOutcome,
    MediaAttachmentRawArtifact,
    MediaBodyMaterializationFailureCategory,
    MediaBodyMaterializationError,
    MediaBodyStoreBudget,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
    MediaPolicyDecision,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_attachment_store import (
    ConfluenceRawAttachmentStore,
)
from knowledgenexus.foundation.ports.confluence_attachment_body_fetch_port import (
    ConfluenceAttachmentBodyFetchError,
    ConfluenceAttachmentBodyTooLargeError,
)
from knowledgenexus.foundation.ports.confluence_raw_attachment_store_port import (
    ConfluenceRawAttachmentStoreError,
    ConfluenceRawAttachmentStoreFailureCategory,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


class _Fetcher:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, str, int]] = []

    def fetch_attachment_body(self, *, attachment_id: str, filename: str, max_bytes: int):
        self.calls.append((attachment_id, filename, max_bytes))
        return self.response


class _Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.published: list[MediaAttachmentBodyEnvelope] = []

    def resolve_attachment_path(self, *, attachment_id: str, content_hash: str) -> Path:
        return self.root / "confluence" / "attachments" / attachment_id / f"{content_hash}.json"

    def publish_attachment(self, *, envelope: MediaAttachmentBodyEnvelope) -> MediaAttachmentRawArtifact:
        self.published.append(envelope)
        digest = hashlib.sha256(envelope.body_bytes).hexdigest()
        return MediaAttachmentRawArtifact(
            path=self.resolve_attachment_path(
                attachment_id=envelope.attachment_id,
                content_hash=digest,
            ),
            attachment_id=envelope.attachment_id,
            body_sha256=digest,
            byte_count=len(envelope.body_bytes),
            raw_uri=f"raw://confluence/attachments/{envelope.attachment_id}/{digest}",
            outcome=MediaAttachmentPublicationOutcome.PUBLISHED,
        )

    def read_attachment(self, *, attachment_id: str, content_hash: str) -> MediaAttachmentBodyEnvelope:
        if not self.published:
            raise FileNotFoundError
        return self.published[-1]


class _RaisingFetcher:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch_attachment_body(self, **_: object) -> object:
        raise self.error


class _RaisingStore(_Store):
    def __init__(
        self,
        root: Path,
        *,
        resolve_error: Exception | None = None,
        publish_error: Exception | None = None,
    ) -> None:
        super().__init__(root)
        self.resolve_error = resolve_error
        self.publish_error = publish_error

    def resolve_attachment_path(self, *, attachment_id: str, content_hash: str) -> Path:
        if self.resolve_error is not None:
            raise self.resolve_error
        return super().resolve_attachment_path(attachment_id=attachment_id, content_hash=content_hash)

    def publish_attachment(self, *, envelope: MediaAttachmentBodyEnvelope) -> MediaAttachmentRawArtifact:
        if self.publish_error is not None:
            raise self.publish_error
        return super().publish_attachment(envelope=envelope)


class _ForgedArtifactStore(_Store):
    def publish_attachment(self, *, envelope: MediaAttachmentBodyEnvelope) -> MediaAttachmentRawArtifact:
        return object.__new__(MediaAttachmentRawArtifact)


def _observation(size_bytes: int | None = 4) -> ConfluenceAttachmentObservation:
    return ConfluenceAttachmentObservation(
        attachment_id="2000",
        parent_page_id="1000",
        filename="diagram.drawio",
        mime_type="application/xml",
        size_bytes=size_bytes,
        source_version="4",
        updated_at=None,
        crawled_at="2026-08-05T00:00:00Z",
    )


def _use_case(fetcher: object, store: object) -> FetchAndStoreConfluenceAttachmentBody:
    return FetchAndStoreConfluenceAttachmentBody(
        body_fetcher=fetcher,
        raw_attachment_store=store,
        budget=MediaBodyStoreBudget(
            max_body_bytes=100,
            max_total_bytes=1000,
            minimum_free_disk_reserve_bytes=0,
        ),
        schema_validator=FoundationSchemaValidator(),
    )


def test_happy_path_downloads_once_and_builds_schema_valid_asset(tmp_path: Path) -> None:
    fetcher = _Fetcher(RawHttpObservation(status_code=200, body=b"body"))
    store = _Store(tmp_path)
    result = _use_case(fetcher, store).execute(
        observation=_observation(),
        decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
    )
    assert result.asset["download_status"] == "downloaded"
    assert result.asset["processing_status"] == "not_processed"
    assert result.asset["content_hash"] == hashlib.sha256(b"body").hexdigest()
    assert len(fetcher.calls) == 1
    assert len(store.published) == 1


def test_happy_path_with_concrete_store_publishes_canonical_envelope(tmp_path: Path) -> None:
    fetcher = _Fetcher(RawHttpObservation(status_code=200, body=b"body"))
    budget = MediaBodyStoreBudget(
        max_body_bytes=100,
        max_total_bytes=1000,
        minimum_free_disk_reserve_bytes=0,
    )
    store = ConfluenceRawAttachmentStore(data_root=tmp_path, budget=budget)
    result = FetchAndStoreConfluenceAttachmentBody(
        body_fetcher=fetcher,
        raw_attachment_store=store,
        budget=budget,
        schema_validator=FoundationSchemaValidator(),
    ).execute(
        observation=_observation(),
        decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
    )
    assert result.artifact.path.exists()
    assert store.read_attachment(
        attachment_id="2000", content_hash=result.artifact.body_sha256
    ).body_bytes == b"body"


def test_non_download_policy_fails_before_fetch() -> None:
    fetcher = _Fetcher(RawHttpObservation(status_code=200, body=b"body"))
    store = _Store(Path("C:/synthetic-root"))
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(fetcher, store).execute(
            observation=_observation(),
            decision=MediaPolicyDecision(attachment_id="2000", policy="metadata_only"),
        )
    assert error.value.category is MediaBodyMaterializationFailureCategory.INVALID_POLICY
    assert fetcher.calls == []
    assert store.published == []


@pytest.mark.parametrize(
    "response,category",
    [
        (RawHttpObservation(status_code=404, body=b"body"), MediaBodyMaterializationFailureCategory.HTTP),
        (object(), MediaBodyMaterializationFailureCategory.FETCH),
    ],
)
def test_malformed_fetch_results_fail_closed(response: object, category) -> None:
    fetcher = _Fetcher(response)
    store = _Store(Path("C:/synthetic-root"))
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(fetcher, store).execute(
            observation=_observation(),
            decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
        )
    assert error.value.category is category
    assert store.published == []


def test_declared_size_mismatch_is_rejected_without_publish(tmp_path: Path) -> None:
    fetcher = _Fetcher(RawHttpObservation(status_code=200, body=b"other"))
    store = _Store(tmp_path)
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(fetcher, store).execute(
            observation=_observation(size_bytes=4),
            decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
        )
    assert error.value.category is MediaBodyMaterializationFailureCategory.METADATA_MISMATCH
    assert store.published == []


def test_forged_budget_fails_before_boundary_access() -> None:
    with pytest.raises(MediaBodyMaterializationError) as error:
        FetchAndStoreConfluenceAttachmentBody(
            body_fetcher=_Fetcher(RawHttpObservation(status_code=200, body=b"body")),
            raw_attachment_store=_Store(Path("C:/synthetic-root")),
            budget=object.__new__(MediaBodyStoreBudget),
            schema_validator=FoundationSchemaValidator(),
        )
    assert error.value.category is MediaBodyMaterializationFailureCategory.INVALID_INPUT


def test_forged_fetch_observation_fails_closed() -> None:
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(
            _Fetcher(object.__new__(RawHttpObservation)),
            _Store(Path("C:/synthetic-root")),
        ).execute(
            observation=_observation(),
            decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
        )
    assert error.value.category is MediaBodyMaterializationFailureCategory.FETCH


def test_unexpected_fetch_exception_is_sanitized() -> None:
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(
            _RaisingFetcher(RuntimeError("secret/path/body")),
            _Store(Path("C:/synthetic-root")),
        ).execute(
            observation=_observation(),
            decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
        )
    assert error.value.category is MediaBodyMaterializationFailureCategory.FETCH
    assert "secret/path" not in str(error.value)


@pytest.mark.parametrize(
    "store_error,category",
    [
        (
            RuntimeError("secret/path/resolve"),
            MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID,
        ),
        (
            RuntimeError("secret/path/publish"),
            MediaBodyMaterializationFailureCategory.RAW_PUBLICATION_FAILURE,
        ),
    ],
)
def test_unexpected_store_exceptions_are_sanitized(
    store_error: Exception,
    category: MediaBodyMaterializationFailureCategory,
) -> None:
    kwargs = (
        {"resolve_error": store_error}
        if category is MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID
        else {"publish_error": store_error}
    )
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(
            _Fetcher(RawHttpObservation(status_code=200, body=b"body")),
            _RaisingStore(Path("C:/synthetic-root"), **kwargs),
        ).execute(
            observation=_observation(),
            decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
        )
    assert error.value.category is category
    assert "secret/path" not in str(error.value)


def test_forged_store_artifact_fails_closed() -> None:
    with pytest.raises(MediaBodyMaterializationError) as error:
        _use_case(
            _Fetcher(RawHttpObservation(status_code=200, body=b"body")),
            _ForgedArtifactStore(Path("C:/synthetic-root")),
        ).execute(
            observation=_observation(),
            decision=MediaPolicyDecision(attachment_id="2000", policy="download_and_process"),
        )
    assert error.value.category is MediaBodyMaterializationFailureCategory.RAW_ARTIFACT_INVALID


def test_fetch_port_errors_are_category_only() -> None:
    with pytest.raises(TypeError):
        ConfluenceAttachmentBodyFetchError("secret/path")  # type: ignore[arg-type]
    error = ConfluenceAttachmentBodyTooLargeError()
    assert "secret/path" not in repr(error)


def test_store_error_rejects_unknown_category() -> None:
    with pytest.raises(TypeError):
        ConfluenceRawAttachmentStoreError("secret/path")  # type: ignore[arg-type]
    error = ConfluenceRawAttachmentStoreError(
        ConfluenceRawAttachmentStoreFailureCategory.RAW_ARTIFACT_INVALID
    )
    assert repr(error) == "ConfluenceRawAttachmentStoreError(category='raw_artifact_invalid')"
