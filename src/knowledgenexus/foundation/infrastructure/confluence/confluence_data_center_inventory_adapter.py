from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Iterator, Mapping

from knowledgenexus.foundation.domain.models.confluence_page_metadata import (
    ConfluencePageMetadata,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_data_center_page_metadata_mapper import (  # noqa: E501
    ConfluenceDataCenterPageMetadataMapper,
    ConfluenceDataCenterPayloadError,
)
from knowledgenexus.foundation.infrastructure.confluence.confluence_http_transport import (  # noqa: E501
    ConfluenceHttpError,
    ConfluenceHttpTransport,
)


_ROOT_PATH_TEMPLATE = "/rest/api/content/{page_id}"
_SEARCH_PATH = "/rest/api/search"
_ROOT_EXPAND = "space,version"
_SEARCH_EXPAND = (
    "content.ancestors,content.space,content.version,content.metadata.labels"
)
_SAFE_SPACE_KEY = re.compile(r"\A[A-Za-z0-9._-]+\Z")
_ASCII_PAGE_ID = re.compile(r"\A[0-9]+\Z")


class ConfluenceDataCenterRequestError(RuntimeError):
    """A safe operation-scoped wrapper around a Confluence HTTP failure."""


class ConfluenceDataCenterPaginationError(RuntimeError):
    """Data Center pagination did not terminate within its explicit budget."""


class ConfluenceDataCenterInventoryAdapter:
    """Data Center implementation of the normalized inventory port."""

    def __init__(
        self,
        *,
        transport: ConfluenceHttpTransport,
        max_search_pages: int,
    ) -> None:
        if isinstance(max_search_pages, bool) or not isinstance(
            max_search_pages, int
        ):
            raise TypeError("max_search_pages expects an integer")
        if max_search_pages <= 0:
            raise ValueError("max_search_pages must be positive")
        self._transport = transport
        self._max_search_pages = max_search_pages

    def iter_page_metadata(
        self,
        *,
        space_key: str,
        root_page_id: str,
        page_size: int,
    ) -> Iterable[ConfluencePageMetadata]:
        checked_space_key = _require_space_key(space_key)
        checked_root_page_id = _require_root_page_id(root_page_id)
        checked_page_size = _require_page_size(page_size)
        return self._iter_page_metadata(
            space_key=checked_space_key,
            root_page_id=checked_root_page_id,
            page_size=checked_page_size,
        )

    def _iter_page_metadata(
        self,
        *,
        space_key: str,
        root_page_id: str,
        page_size: int,
    ) -> Iterator[ConfluencePageMetadata]:
        root_payload = self._get_root_payload(root_page_id=root_page_id)
        _require_matching_root_space(
            payload=root_payload,
            expected_space_key=space_key,
        )
        yield ConfluenceDataCenterPageMetadataMapper.map_root(
            payload=root_payload,
            expected_root_page_id=root_page_id,
            expected_space_key=space_key,
        )
        yield from self._iter_descendants(
            space_key=space_key,
            root_page_id=root_page_id,
            page_size=page_size,
        )

    def _get_root_payload(
        self,
        *,
        root_page_id: str,
    ) -> Mapping[str, object]:
        path = _ROOT_PATH_TEMPLATE.format(
            page_id=urllib.parse.quote(root_page_id, safe="")
        )
        try:
            return self._transport.get_json(
                path=path,
                query={"expand": _ROOT_EXPAND},
            )
        except ConfluenceHttpError as exc:
            raise ConfluenceDataCenterRequestError(
                f"root fetch failed: {exc}"
            ) from exc

    def _iter_descendants(
        self,
        *,
        space_key: str,
        root_page_id: str,
        page_size: int,
    ) -> Iterator[ConfluencePageMetadata]:
        cql = (
            f'space="{space_key}" and ancestor={root_page_id} and type=page'
        )
        start = 0

        for _ in range(self._max_search_pages):
            try:
                payload = self._transport.get_json(
                    path=_SEARCH_PATH,
                    query={
                        "cql": cql,
                        "expand": _SEARCH_EXPAND,
                        "limit": str(page_size),
                        "start": str(start),
                    },
                )
            except ConfluenceHttpError as exc:
                raise ConfluenceDataCenterRequestError(
                    f"search window failed at start {start}: {exc}"
                ) from exc

            page = ConfluenceDataCenterPageMetadataMapper.parse_search_page(
                payload=payload,
                expected_start=start,
                expected_limit=page_size,
                selected_root_page_id=root_page_id,
                expected_space_key=space_key,
            )
            yield from page.items
            if page.is_terminal:
                return

            next_start = page.start + page.size
            if next_start <= page.start:
                raise ConfluenceDataCenterPayloadError(
                    "search page response did not advance pagination"
                )
            start = next_start

        raise ConfluenceDataCenterPaginationError(
            "descendant search exceeded max_search_pages before termination"
        )


def _require_space_key(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("space_key expects a string")
    if _SAFE_SPACE_KEY.fullmatch(value) is None:
        raise ValueError("space_key contains characters that are unsafe for CQL")
    return value


def _require_root_page_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("root_page_id expects a string")
    if _ASCII_PAGE_ID.fullmatch(value) is None:
        raise ValueError("root_page_id must contain ASCII decimal digits only")
    return value


def _require_page_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("page_size expects an integer")
    if value <= 0:
        raise ValueError("page_size must be positive")
    return value


def _require_matching_root_space(
    *,
    payload: object,
    expected_space_key: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise ConfluenceDataCenterPayloadError(
            "root response must be an object"
        )
    space = payload.get("space")
    if not isinstance(space, Mapping):
        raise ConfluenceDataCenterPayloadError(
            "root response.space must be an object"
        )
    observed_space_key = space.get("key")
    if not isinstance(observed_space_key, str) or observed_space_key == "":
        raise ConfluenceDataCenterPayloadError(
            "root response.space.key must be a non-empty string"
        )
    if observed_space_key != expected_space_key:
        raise ConfluenceDataCenterPayloadError(
            "root response.space.key must match the expected space key"
        )
