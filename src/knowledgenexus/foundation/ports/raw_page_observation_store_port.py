from __future__ import annotations

from typing import Protocol

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
)
from knowledgenexus.foundation.domain.models.raw_observation_artifact import (
    RawObservationArtifact,
)


class RawPageReadError(Exception):
    """A preserved raw page could not be read safely."""


class RawObservationStoreError(Exception):
    """A raw page-adjacent response could not be preserved safely."""


class RawPageReadPort(Protocol):
    def read_page(self, *, page_id: str) -> bytes: ...


class RawObservationStorePort(Protocol):
    def write_restriction(
        self,
        *,
        selected_page_id: str,
        target_page_id: str,
        raw_bytes: bytes,
    ) -> RawObservationArtifact: ...

    def write_attachment_window(
        self,
        *,
        selected_page_id: str,
        request: AttachmentMetadataRequest,
        raw_bytes: bytes,
    ) -> RawObservationArtifact: ...
