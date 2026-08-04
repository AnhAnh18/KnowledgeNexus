from __future__ import annotations

import hashlib
from pathlib import Path

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageArtifact,
    ConfluenceRawPageEnvelope,
    ConfluenceRawPagePublicationOutcome,
    ConfluenceRawPageStoreFailureCategory as FailureCategory,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.infrastructure.raw_store.confluence_raw_restriction_store import (
    _MAX_STABLE_READ_BYTES,
    _bound_read,
    _open_bound_parent,
    _publish_bound,
    _require_plain_directory_chain,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStoreError,
    ConfluenceRawPageStorePort,
)

_GENERATION_RELATIVE_DIR = ("confluence", "generations")


def _fail(category: FailureCategory) -> None:
    raise ConfluenceRawPageStoreError(category) from None


def _require_run_id(value: object) -> CrawlRunId:
    if type(value) is not CrawlRunId:
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
    try:
        rebuilt = CrawlRunId(value.value)
    except Exception:
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
    if rebuilt != value:
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
    return rebuilt


def _require_page_id(value: object) -> str:
    try:
        return require_confluence_page_id(value)
    except (TypeError, ValueError):
        _fail(FailureCategory.RAW_IDENTITY_MISMATCH)


class ConfluenceRawPageGenerationStore(ConfluenceRawPageStorePort):
    """Publishes immutable generation-scoped raw-page evidence offline."""

    def __init__(self, *, raw_root: Path) -> None:
        if not isinstance(raw_root, Path) or not raw_root.is_absolute():
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        if any(part in {".", ".."} for part in raw_root.parts):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        try:
            _require_plain_directory_chain(raw_root)
        except Exception:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        self._raw_root = raw_root

    def resolve_page_path(self, *, run_id: CrawlRunId, page_id: str) -> Path:
        run = _require_run_id(run_id)
        page = _require_page_id(page_id)
        path = self._raw_root.joinpath(
            *_GENERATION_RELATIVE_DIR,
            str(run),
            "pages",
            f"{page}.json",
        )
        try:
            path.relative_to(self._raw_root)
        except ValueError:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        return path

    def publish_page(self, *, envelope: ConfluenceRawPageEnvelope) -> ConfluenceRawPageArtifact:
        if type(envelope) is not ConfluenceRawPageEnvelope:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        run = _require_run_id(envelope.run_id)
        if envelope.generation_id != run:
            _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
        target = self.resolve_page_path(run_id=run, page_id=envelope.page_id)
        try:
            content = envelope.to_bytes()
        except Exception:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        if len(content) > _MAX_STABLE_READ_BYTES:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        self._ensure_target_parent(target.parent)
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                published = _publish_bound(parent_handle, target.name, content)
            if not published:
                return self._replay_result(target=target, expected=content, run_id=run)
            return self._artifact(
                path=target,
                run_id=run,
                page_id=envelope.page_id,
                content=content,
                outcome=ConfluenceRawPagePublicationOutcome.PUBLISHED,
            )
        except ConfluenceRawPageStoreError:
            raise
        except (OSError, TypeError, ValueError):
            _fail(FailureCategory.RAW_PUBLICATION_FAILURE)

    def read_page(self, *, run_id: CrawlRunId, page_id: str) -> ConfluenceRawPageEnvelope:
        run = _require_run_id(run_id)
        page = _require_page_id(page_id)
        target = self.resolve_page_path(run_id=run, page_id=page)
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                content = _bound_read(parent_handle, target.name)
        except ConfluenceRawPageStoreError:
            raise
        except (FileNotFoundError, OSError, ValueError, TypeError, OverflowError):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        return self._parse_bound(content=content, run_id=run, page_id=page)

    def _ensure_target_parent(self, parent: Path) -> None:
        try:
            parent.relative_to(self._raw_root)
        except ValueError:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        try:
            with _open_bound_parent(parent, create=True):
                pass
        except (FileNotFoundError, OSError, TypeError, ValueError):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)

    def _replay_result(
        self,
        *,
        target: Path,
        expected: bytes,
        run_id: CrawlRunId,
    ) -> ConfluenceRawPageArtifact:
        try:
            with _open_bound_parent(target.parent, create=False) as parent_handle:
                existing = _bound_read(parent_handle, target.name)
        except ConfluenceRawPageStoreError:
            raise
        except (FileNotFoundError, OSError, ValueError, TypeError, OverflowError):
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        envelope = self._parse_bound(
            content=existing,
            run_id=run_id,
            page_id=target.stem,
        )
        if existing != expected:
            _fail(FailureCategory.RAW_REPLAY_CONFLICT)
        return self._artifact(
            path=target,
            run_id=run_id,
            page_id=envelope.page_id,
            content=existing,
            outcome=ConfluenceRawPagePublicationOutcome.REUSED,
        )

    @staticmethod
    def _parse_bound(
        *,
        content: bytes,
        run_id: CrawlRunId,
        page_id: str,
    ) -> ConfluenceRawPageEnvelope:
        try:
            envelope = ConfluenceRawPageEnvelope.from_bytes(content)
        except Exception:
            _fail(FailureCategory.RAW_ARTIFACT_INVALID)
        if (
            envelope.run_id != run_id
            or envelope.generation_id != run_id
            or envelope.page_id != _require_page_id(page_id.removesuffix(".json"))
        ):
            _fail(FailureCategory.RAW_IDENTITY_MISMATCH)
        return envelope

    @staticmethod
    def _artifact(
        *,
        path: Path,
        run_id: CrawlRunId,
        page_id: str,
        content: bytes,
        outcome: ConfluenceRawPagePublicationOutcome,
    ) -> ConfluenceRawPageArtifact:
        return ConfluenceRawPageArtifact(
            path=path,
            run_id=run_id,
            page_id=page_id,
            raw_sha256=hashlib.sha256(content).hexdigest(),
            byte_count=len(content),
            outcome=outcome,
        )


__all__ = ["ConfluenceRawPageGenerationStore"]
