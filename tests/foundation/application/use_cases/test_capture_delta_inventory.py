from __future__ import annotations

import hashlib
import json

import pytest

from knowledgenexus.foundation.application.use_cases.capture_delta_inventory import (
    CaptureDeltaInventory,
    DeltaInventoryCaptureError,
    DeltaInventoryCaptureRequest,
    scope_identity,
    selection_identity,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import ConfluenceRawPageEnvelope
from knowledgenexus.foundation.domain.models.delta_inventory import (
    CurrentSelectionPage,
    DeltaInventoryEnvelope,
    DeltaInventoryScope,
    PriorConfluenceDocument,
)


RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")


class Response:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class Transport:
    request_profile_version = "m7-confluence-request-profile-v1"
    checkpoint_bound = True

    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls = 0

    def get_response_bytes(self, *, path: str, query: dict[str, str]) -> Response:
        self.calls += 1
        return self.response

    def snapshot(self):
        return type("Snapshot", (), {"requests_started_for_run": self.calls})()


class RawStore:
    def __init__(self, existing: ConfluenceRawPageEnvelope | None = None) -> None:
        self.existing = existing
        self.published: list[ConfluenceRawPageEnvelope] = []

    def read_page(self, *, run_id: CrawlRunId, page_id: str) -> ConfluenceRawPageEnvelope:
        if self.existing is None:
            raise FileNotFoundError("missing")
        return self.existing

    def publish_page(self, *, envelope: ConfluenceRawPageEnvelope) -> object:
        self.published.append(envelope)
        return object()


class ArtifactStore:
    def __init__(self) -> None:
        self.envelope = None

    def publish(self, *, envelope: DeltaInventoryEnvelope):
        self.envelope = envelope


def _request(transport: object, raw: object, artifact: object) -> DeltaInventoryCaptureRequest:
    selection = ()
    scope = DeltaInventoryScope(("1",))
    return DeltaInventoryCaptureRequest(
        RUN,
        RUN,
        "v20260805-000000-000000Z",
        selection_identity(selection),
        scope_identity(scope),
        (PriorConfluenceDocument("1", "confluence:page:1", "v1"),),
        selection,
        scope,
        transport,
        raw,
        artifact,
    )


def test_capture_publishes_raw_before_derived_inventory_and_preserves_404_detail() -> None:
    transport = Transport(Response(404, b"not found"))
    raw = RawStore()
    artifact = ArtifactStore()
    envelope = CaptureDeltaInventory().execute(_request(transport, raw, artifact))
    assert transport.calls == 1
    assert len(raw.published) == 1
    assert artifact.envelope is envelope
    assert envelope.entries[0].state.value == "source_deleted"
    assert envelope.entries[0].detail == "confluence_404_may_mask_access_revoked"


def test_matching_raw_replay_performs_no_get() -> None:
    raw_envelope = ConfluenceRawPageEnvelope.capture(
        run_id=RUN, page_id="1", source_version="v1", http_status=404, body_bytes=b"not found"
    )
    transport = Transport(Response(500, b"must not fetch"))
    raw = RawStore(raw_envelope)
    artifact = ArtifactStore()
    result = CaptureDeltaInventory().execute(_request(transport, raw, artifact))
    assert transport.calls == 0
    assert result.entries[0].state.value == "source_deleted"


def test_wrong_run_replay_fails_without_get() -> None:
    other = CrawlRunId("123e4567-e89b-42d3-a456-426614174001")
    raw_envelope = ConfluenceRawPageEnvelope.capture(
        run_id=other, page_id="1", source_version="v1", http_status=404, body_bytes=b"not found"
    )
    transport = Transport(Response(500, b"must not fetch"))
    with pytest.raises(DeltaInventoryCaptureError):
        CaptureDeltaInventory().execute(_request(transport, RawStore(raw_envelope), ArtifactStore()))
    assert transport.calls == 0


def test_malformed_200_body_fails_closed() -> None:
    transport = Transport(Response(200, b'{"id":"1","version":{"number":2},"ancestors":[{"id":2}]}'))
    with pytest.raises(DeltaInventoryCaptureError):
        CaptureDeltaInventory().execute(_request(transport, RawStore(), ArtifactStore()))
    assert transport.calls == 1


def test_inventory_envelope_round_trips_canonically() -> None:
    transport = Transport(Response(404, b"not found"))
    raw = RawStore()
    artifact = ArtifactStore()
    envelope = CaptureDeltaInventory().execute(_request(transport, raw, artifact))
    serialized = envelope.to_bytes()
    assert DeltaInventoryEnvelope.from_bytes(serialized).to_bytes() == serialized
    assert hashlib.sha256(serialized).hexdigest() == hashlib.sha256(envelope.to_bytes()).hexdigest()


@pytest.mark.parametrize("bad", [None, object()])
def test_invalid_capture_boundary_is_sanitized(bad: object) -> None:
    with pytest.raises(DeltaInventoryCaptureError) as exc:
        CaptureDeltaInventory().execute(bad)
    assert exc.value.category.value == "invalid_input"
