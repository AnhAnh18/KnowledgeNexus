from __future__ import annotations

import pytest

from knowledgenexus.foundation.application.use_cases.process_confluence_media_attachment import (
    ProcessConfluenceMediaAttachment,
)
from knowledgenexus.foundation.application.use_cases.process_confluence_media_batch import (
    MediaBatchProcessingError,
    ProcessConfluenceMediaBatch,
)
from knowledgenexus.foundation.domain.models.media_body_materialization import (
    MediaAttachmentBodyEnvelope,
)
from knowledgenexus.foundation.domain.models.media_materialization import (
    ConfluenceAttachmentObservation,
)


def _item(attachment_id: str, filename: str) -> tuple[MediaAttachmentBodyEnvelope, ConfluenceAttachmentObservation]:
    envelope = MediaAttachmentBodyEnvelope(
        format_version="1",
        evidence_kind="confluence_attachment_body",
        attachment_id=attachment_id,
        parent_page_id="1000",
        filename=filename,
        source_version="1",
        http_status=200,
        body_encoding="base64",
        body_bytes=b"body",
    )
    observation = ConfluenceAttachmentObservation(
        attachment_id=attachment_id,
        parent_page_id="1000",
        filename=filename,
        mime_type="application/pdf",
        size_bytes=4,
        source_version="1",
        updated_at=None,
        crawled_at="2026-08-08T00:00:00Z",
    )
    return envelope, observation


def test_batch_returns_sorted_assets_and_failure_categories() -> None:
    result = ProcessConfluenceMediaBatch(
        processor=ProcessConfluenceMediaAttachment(),
    ).execute(items=(_item("2001", "b.pdf"), _item("2000", "a.pdf")))
    assert [asset["media_id"] for asset in result.assets] == [
        "confluence:attachment:2000",
        "confluence:attachment:2001",
    ]
    assert result.failures == ("capability_unavailable", "capability_unavailable")


@pytest.mark.parametrize("items", [None, object(), (object(),)])
def test_batch_rejects_malformed_items_before_processing(items: object) -> None:
    with pytest.raises(MediaBatchProcessingError):
        ProcessConfluenceMediaBatch(processor=ProcessConfluenceMediaAttachment()).execute(items=items)
