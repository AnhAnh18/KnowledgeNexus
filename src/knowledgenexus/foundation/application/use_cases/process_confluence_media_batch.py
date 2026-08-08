from __future__ import annotations

import copy
from dataclasses import dataclass

from knowledgenexus.foundation.application.use_cases.process_confluence_media_attachment import (
    ProcessConfluenceMediaAttachment,
)
from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
)
from knowledgenexus.foundation.domain.models.media_processing import (
    MediaProcessingResult,
)


class MediaBatchProcessingError(Exception):
    """Sanitized failure for the atomic media batch boundary."""


@dataclass(frozen=True)
class MediaBatchProcessingResult:
    assets: tuple[dict[str, object], ...]
    details: tuple[object, ...]
    failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.assets) is not tuple or any(type(asset) is not dict for asset in self.assets):
            raise TypeError("media batch assets are invalid")
        if type(self.details) is not tuple or any(type(detail) is not tuple for detail in self.details):
            raise TypeError("media batch details are invalid")
        if type(self.failures) is not tuple or any(type(value) is not str or not value for value in self.failures):
            raise TypeError("media batch failures are invalid")
        ids = tuple(asset.get("media_id") for asset in self.assets)
        if any(type(value) is not str or not value for value in ids) or len(ids) != len(set(ids)) or ids != tuple(sorted(ids)):
            raise ValueError("media batch asset ordering is invalid")
        object.__setattr__(self, "assets", tuple(copy.deepcopy(asset) for asset in self.assets))
        object.__setattr__(self, "details", tuple(tuple(copy.deepcopy(detail) for detail in details) for details in self.details))


class ProcessConfluenceMediaBatch:
    """Process materialized attachments atomically and deterministically."""

    def __init__(self, *, processor: object) -> None:
        if type(processor) is not ProcessConfluenceMediaAttachment:
            raise TypeError("processor is invalid")
        self._processor = processor

    def execute(self, *, items: object) -> MediaBatchProcessingResult:
        if type(items) is not tuple:
            raise MediaBatchProcessingError("invalid input")
        normalized: list[tuple[MediaAttachmentBodyEnvelope, ConfluenceAttachmentObservation]] = []
        for item in items:
            if type(item) is not tuple or len(item) != 2 or type(item[0]) is not MediaAttachmentBodyEnvelope or type(item[1]) is not ConfluenceAttachmentObservation:
                raise MediaBatchProcessingError("invalid input")
            normalized.append((item[0], item[1]))
        results: list[MediaProcessingResult] = []
        try:
            for envelope, observation in normalized:
                result = self._processor.execute(envelope=envelope, observation=observation)
                if type(result) is not MediaProcessingResult:
                    raise TypeError("invalid processor result")
                results.append(result)
        except Exception:
            raise MediaBatchProcessingError("media batch processing failed") from None
        assets = sorted((copy.deepcopy(result.asset) for result in results), key=lambda asset: str(asset["media_id"]))
        if len({asset["media_id"] for asset in assets}) != len(assets):
            raise MediaBatchProcessingError("duplicate media IDs")
        detail_groups = tuple(tuple(copy.deepcopy(result.details)) for result in results)
        failures = tuple(sorted(result.failure_category.value for result in results if result.failure_category is not None))
        return MediaBatchProcessingResult(
            assets=tuple(assets),
            details=detail_groups,
            failures=failures,
        )


__all__ = ["MediaBatchProcessingError", "MediaBatchProcessingResult", "ProcessConfluenceMediaBatch"]
