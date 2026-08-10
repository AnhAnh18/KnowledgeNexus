from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageArtifact,
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.domain.rules.confluence_page_id import (
    require_confluence_page_id,
)
from knowledgenexus.foundation.ports.confluence_page_fetch_port import (
    ConfluencePageFetchError,
    ConfluencePageFetchPort,
    ConfluencePageTooLargeError,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStoreError,
    ConfluenceRawPageStorePort,
)


class GenerationRawPageFetchError(Exception):
    """Sanitized failure from a generation-bound page fetch."""

    def __init__(self, category: str) -> None:
        if type(category) is not str or not category:
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class GenerationRawPageFetchResult:
    """Published artifact metadata; raw response bytes never escape."""

    artifact: ConfluenceRawPageArtifact


_CATEGORIES = {
    "invalid_run_id",
    "invalid_page_id",
    "http",
    "response_size_limit",
    "malformed_json",
    "non_object_json",
    "identity_mismatch",
    "source_version_invalid",
    "store",
}


def _fail(category: str, cause: BaseException | None = None) -> None:
    if category not in _CATEGORIES:
        raise ValueError("unknown failure category")
    raise GenerationRawPageFetchError(category) from cause


def _reject_duplicate_keys(pairs: list[tuple[object, object]]) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("malformed_json")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail("malformed_json")


def _source_version_and_identity(*, body: bytes, page_id: str) -> str:
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except GenerationRawPageFetchError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _fail("malformed_json", exc)
    if not isinstance(payload, Mapping):
        _fail("non_object_json")
    observed_id = payload.get("id")
    if isinstance(observed_id, bool) or not isinstance(observed_id, (str, int)):
        _fail("identity_mismatch")
    if str(observed_id) != page_id:
        _fail("identity_mismatch")
    version = payload.get("version")
    if not isinstance(version, Mapping):
        _fail("source_version_invalid")
    number = version.get("number")
    if isinstance(number, bool) or type(number) is not int or number <= 0:
        _fail("source_version_invalid")
    return str(number)


class FetchAndStoreConfluenceRawPageGeneration:
    """Fetch one page and publish exact bytes into a generation-scoped store."""

    def __init__(
        self,
        *,
        page_fetcher: ConfluencePageFetchPort,
        raw_page_store: ConfluenceRawPageStorePort,
    ) -> None:
        if not callable(getattr(page_fetcher, "fetch_page_raw", None)):
            raise TypeError("page_fetcher is invalid")
        if not callable(getattr(raw_page_store, "publish_page", None)):
            raise TypeError("raw_page_store is invalid")
        self._page_fetcher = page_fetcher
        self._raw_page_store = raw_page_store

    def execute(
        self,
        *,
        run_id: CrawlRunId,
        page_id: str,
    ) -> GenerationRawPageFetchResult:
        if type(run_id) is not CrawlRunId:
            _fail("invalid_run_id")
        try:
            run_id = CrawlRunId(run_id.value)
        except Exception as exc:
            _fail("invalid_run_id", exc)
        try:
            page_id = require_confluence_page_id(page_id)
        except (TypeError, ValueError) as exc:
            _fail("invalid_page_id", exc)

        try:
            body = self._page_fetcher.fetch_page_raw(page_id=page_id)
        except ConfluencePageTooLargeError as exc:
            _fail("response_size_limit", exc)
        except ConfluencePageFetchError as exc:
            _fail("http", exc)
        except Exception as exc:
            _fail("http", exc)
        if type(body) is not bytes:
            _fail("http")

        source_version = _source_version_and_identity(body=body, page_id=page_id)
        try:
            envelope = ConfluenceRawPageEnvelope.capture(
                run_id=run_id,
                page_id=page_id,
                source_version=source_version,
                http_status=200,
                body_bytes=body,
            )
            artifact = self._raw_page_store.publish_page(envelope=envelope)
            if type(artifact) is not ConfluenceRawPageArtifact:
                raise TypeError("artifact is invalid")
        except GenerationRawPageFetchError:
            raise
        except (ConfluenceRawPageStoreError, OSError, TypeError, ValueError) as exc:
            _fail("store", exc)
        except Exception as exc:
            _fail("store", exc)
        return GenerationRawPageFetchResult(artifact=artifact)


__all__ = [
    "FetchAndStoreConfluenceRawPageGeneration",
    "GenerationRawPageFetchError",
    "GenerationRawPageFetchResult",
]
