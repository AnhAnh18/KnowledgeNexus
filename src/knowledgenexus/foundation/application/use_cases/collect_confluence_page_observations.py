from __future__ import annotations

from dataclasses import dataclass

from knowledgenexus.foundation.domain.models.confluence_page_observation import (
    AttachmentMetadataRequest,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.domain.rules.confluence_page_observations import (
    ConfluencePageObservationPayloadError,
    build_restriction_observation,
    extract_ordered_restriction_targets,
    parse_attachment_metadata_window,
)
from knowledgenexus.foundation.ports.confluence_page_observation_port import (
    ConfluenceAttachmentMetadataFetchPort,
    ConfluenceObservationFetchError,
    ConfluenceObservationTooLargeError,
    ConfluenceRestrictionFetchPort,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawObservationStoreError,
    RawObservationStorePort,
    RawPageReadError,
    RawPageReadPort,
)

CATEGORY_INVALID_PAGE_ID = "invalid_page_id"
CATEGORY_RAW_PAGE_INPUT = "raw_page_input"
CATEGORY_RESTRICTION_HTTP = "restriction_http"
CATEGORY_ATTACHMENT_HTTP = "attachment_http"
CATEGORY_RESPONSE_SIZE_LIMIT = "response_size_limit"
CATEGORY_STORE = "store"
CATEGORY_ATTACHMENT_PAYLOAD = "attachment_payload"
CATEGORY_PAGINATION = "pagination"


class PageObservationCollectionError(Exception):
    """A sanitized, category-tagged M6B collection failure."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True, repr=False)
class PageObservationCollectionResult:
    restriction_observations: tuple[dict[str, object], ...]
    attachment_observations: tuple[dict[str, object], ...]
    attachment_window_count: int

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class CollectConfluencePageObservations:
    """Collect and preserve adjacent observations for one preserved raw page."""

    def __init__(
        self,
        *,
        raw_page_reader: RawPageReadPort,
        restriction_fetcher: ConfluenceRestrictionFetchPort,
        attachment_fetcher: ConfluenceAttachmentMetadataFetchPort,
        raw_observation_store: RawObservationStorePort,
        attachment_page_size: int,
        max_attachment_pages: int,
    ) -> None:
        self._raw_page_reader = raw_page_reader
        self._restriction_fetcher = restriction_fetcher
        self._attachment_fetcher = attachment_fetcher
        self._raw_observation_store = raw_observation_store
        self._attachment_page_size = _require_positive_int(
            attachment_page_size, name="attachment_page_size"
        )
        self._max_attachment_pages = _require_positive_int(
            max_attachment_pages, name="max_attachment_pages"
        )

    def execute(self, *, selected_page_id: str) -> PageObservationCollectionResult:
        try:
            selected_page_id = require_confluence_page_id(selected_page_id)
        except (TypeError, ValueError) as exc:
            raise PageObservationCollectionError(CATEGORY_INVALID_PAGE_ID) from exc

        try:
            raw_page = self._raw_page_reader.read_page(page_id=selected_page_id)
            targets = extract_ordered_restriction_targets(
                raw_page=raw_page,
                selected_page_id=selected_page_id,
            )
        except (RawPageReadError, OSError, ConfluencePageObservationPayloadError) as exc:
            raise PageObservationCollectionError(CATEGORY_RAW_PAGE_INPUT) from exc

        restrictions = self._collect_restrictions(
            selected_page_id=selected_page_id,
            targets=targets,
        )
        attachments, window_count = self._collect_attachments(
            selected_page_id=selected_page_id
        )
        return PageObservationCollectionResult(
            restriction_observations=tuple(restrictions),
            attachment_observations=tuple(attachments),
            attachment_window_count=window_count,
        )

    def _collect_restrictions(
        self,
        *,
        selected_page_id: str,
        targets: tuple[str, ...],
    ) -> list[dict[str, object]]:
        observations: list[dict[str, object]] = []
        for target_page_id in targets:
            try:
                response = self._restriction_fetcher.fetch_view_restriction(
                    page_id=target_page_id
                )
            except ConfluenceObservationTooLargeError as exc:
                raise PageObservationCollectionError(
                    CATEGORY_RESPONSE_SIZE_LIMIT
                ) from exc
            except ConfluenceObservationFetchError as exc:
                raise PageObservationCollectionError(CATEGORY_RESTRICTION_HTTP) from exc
            try:
                self._raw_observation_store.write_restriction(
                    selected_page_id=selected_page_id,
                    target_page_id=target_page_id,
                    raw_bytes=response.body,
                )
            except (RawObservationStoreError, OSError, TypeError, ValueError) as exc:
                raise PageObservationCollectionError(CATEGORY_STORE) from exc
            try:
                observation = build_restriction_observation(
                    target_page_id=target_page_id,
                    response=response,
                )
            except ConfluencePageObservationPayloadError as exc:
                # The exact body has already been preserved. An unexpected HTTP
                # status remains an operational failure, never an unavailable
                # restriction observation.
                raise PageObservationCollectionError(
                    CATEGORY_RESTRICTION_HTTP
                ) from exc
            observations.append(observation)
        return observations

    def _collect_attachments(
        self, *, selected_page_id: str
    ) -> tuple[list[dict[str, object]], int]:
        request = AttachmentMetadataRequest(
            start=0,
            limit=self._attachment_page_size,
        )
        seen_requests: set[AttachmentMetadataRequest] = set()
        seen_attachment_ids: set[str] = set()
        observations: list[dict[str, object]] = []

        while True:
            if request in seen_requests:
                raise PageObservationCollectionError(CATEGORY_PAGINATION)
            if len(seen_requests) >= self._max_attachment_pages:
                raise PageObservationCollectionError(CATEGORY_PAGINATION)
            seen_requests.add(request)

            try:
                raw_bytes = self._attachment_fetcher.fetch_attachment_metadata(
                    page_id=selected_page_id,
                    request=request,
                )
            except ConfluenceObservationTooLargeError as exc:
                raise PageObservationCollectionError(
                    CATEGORY_RESPONSE_SIZE_LIMIT
                ) from exc
            except ConfluenceObservationFetchError as exc:
                raise PageObservationCollectionError(CATEGORY_ATTACHMENT_HTTP) from exc

            try:
                self._raw_observation_store.write_attachment_window(
                    selected_page_id=selected_page_id,
                    request=request,
                    raw_bytes=raw_bytes,
                )
            except (RawObservationStoreError, OSError, TypeError, ValueError) as exc:
                raise PageObservationCollectionError(CATEGORY_STORE) from exc

            try:
                parsed = parse_attachment_metadata_window(
                    raw_bytes=raw_bytes,
                    selected_page_id=selected_page_id,
                    request=request,
                )
            except ConfluencePageObservationPayloadError as exc:
                raise PageObservationCollectionError(
                    CATEGORY_ATTACHMENT_PAYLOAD
                ) from exc

            for observation in parsed.attachments:
                attachment_id = observation.get("attachment_id")
                assert isinstance(attachment_id, str)
                if attachment_id in seen_attachment_ids:
                    raise PageObservationCollectionError(CATEGORY_ATTACHMENT_PAYLOAD)
                seen_attachment_ids.add(attachment_id)
                observations.append(observation)

            if parsed.next_request is None:
                return observations, len(seen_requests)
            if parsed.next_request in seen_requests:
                raise PageObservationCollectionError(CATEGORY_PAGINATION)
            if len(seen_requests) >= self._max_attachment_pages:
                raise PageObservationCollectionError(CATEGORY_PAGINATION)
            request = parsed.next_request


def _require_positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} expects an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
