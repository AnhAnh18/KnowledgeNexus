from __future__ import annotations

import pytest

from knowledgenexus.foundation.application.use_cases.materialize_confluence_media_relations import (
    MaterializeConfluenceMediaRelations,
    MediaRelationMaterializationError,
    MediaRelationMaterializationFailureCategory,
)
from knowledgenexus.foundation.domain.models import (
    ConfluenceAttachmentObservation,
    MediaMaterializationResult,
    MediaPolicyDecision,
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.records import (
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import MediaAssetRecordBuilder


def _documents() -> tuple[dict[str, object], ...]:
    return (
        CanonicalDocumentRecordBuilder.build(
            document_id="confluence:page:1000",
            source_system="confluence",
            source_type="wiki_page",
            normalized_body_text="Page body",
            acl_id="acl:page-1000",
            crawled_at="2026-08-08T00:00:00Z",
            title="Design page",
            space_key="SPEN",
            page_id="1000",
            source_version="7",
        ),
    )


def _chunks() -> tuple[dict[str, object], ...]:
    return (
        ChunkRecordBuilder.build(
            chunk_id="chunk:confluence:0123456789abcdef",
            document_id="confluence:page:1000",
            source_system="confluence",
            source_type="wiki_page",
            text="Page body",
            content_kind="prose",
            language="unknown",
            token_count=2,
            acl_tags=["space:SPEN"],
            chunker_version="1.3.0",
            title="Design page",
            space_key="SPEN",
            page_id="1000",
            source_version="7",
        ),
    )


def _media(*, target: str | None = "diagram.drawio") -> MediaMaterializationResult:
    observation = ConfluenceAttachmentObservation(
        attachment_id="2000",
        parent_page_id="1000",
        filename="diagram.drawio",
        mime_type="application/xml",
        size_bytes=10,
        source_version="7",
        updated_at="2026-08-08T00:00:00Z",
        crawled_at="2026-08-08T00:00:01Z",
    )
    intents = () if target is None else (
        NormalizationReferenceIntent(1, "drawio", "deferred_mvp", target, target),
    )
    return MediaAssetRecordBuilder.build_batch(
        (observation,),
        (MediaPolicyDecision("2000", "download_and_process"),),
        intents,
    )


def test_materializes_resolved_media_edge_and_inherits_relation_ids() -> None:
    result = MaterializeConfluenceMediaRelations().execute(
        documents=_documents(),
        chunks=_chunks(),
        media=_media(),
    )

    assert result.metrics.relations_total == 1
    assert result.metrics.resolved == 1
    assert result.metrics.unresolved_target == 0
    relation = result.relations[0]
    assert relation["relation_type"] == "embeds_media"
    assert relation["resolution_status"] == "resolved"
    assert relation["source_id"] == "confluence:page:1000"
    assert relation["target_id"] == "confluence:attachment:2000"
    assert result.documents[0]["relation_ids"] == [relation["relation_id"]]
    assert result.chunks[0]["relation_ids"] == [relation["relation_id"]]


def test_unresolved_media_reference_uses_stable_external_target_marker() -> None:
    result = MaterializeConfluenceMediaRelations().execute(
        documents=_documents(),
        chunks=_chunks(),
        media=_media(target="missing.png"),
    )

    relation = result.relations[0]
    assert relation["resolution_status"] == "unresolved_target"
    assert relation["target_id"].startswith("confluence:attachment:unresolved-")
    assert relation["target_id"] not in {asset["media_id"] for asset in _media().assets}


def test_materializes_unresolved_include_page_relation() -> None:
    intent = NormalizationReferenceIntent(
        1,
        "include_page",
        "unresolved_target",
        "Included design page",
        "Included design page",
    )
    result = MaterializeConfluenceMediaRelations().execute(
        documents=_documents(),
        chunks=_chunks(),
        media=_media(target=None),
        page_references=(("confluence:page:1000", (intent,)),),
    )
    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation["relation_type"] == "includes_page"
    assert relation["resolution_status"] == "unresolved_target"
    assert relation["target_id"].startswith("confluence:page:unresolved-")


def test_resolves_page_link_by_confluence_page_identity() -> None:
    target_document = dict(_documents()[0])
    target_document.update(
        {
            "document_id": "confluence:page:2000",
            "page_id": "2000",
            "title": "Target page",
        }
    )
    intent = NormalizationReferenceIntent(
        1,
        "page_link",
        "deferred_mvp",
        "confluence:page:2000",
        "confluence:page:2000",
    )
    result = MaterializeConfluenceMediaRelations().execute(
        documents=(_documents()[0], target_document),
        chunks=_chunks(),
        media=_media(target=None),
        page_references=(("confluence:page:1000", (intent,)),),
    )
    relation = result.relations[0]
    assert relation["relation_type"] == "links_to_page"
    assert relation["resolution_status"] == "resolved"
    assert relation["target_id"] == "confluence:page:2000"


@pytest.mark.parametrize("bad_media", [None, object(), (object(),)])
def test_rejects_wrong_runtime_media_before_field_access(bad_media: object) -> None:
    with pytest.raises(MediaRelationMaterializationError) as exc_info:
        MaterializeConfluenceMediaRelations().execute(
            documents=_documents(),
            chunks=_chunks(),
            media=bad_media,
        )
    assert exc_info.value.category == MediaRelationMaterializationFailureCategory.INVALID_INPUT


def test_rejects_missing_source_and_cross_page_target() -> None:
    media = _media()
    with pytest.raises(MediaRelationMaterializationError) as exc_info:
        MaterializeConfluenceMediaRelations().execute(documents=(), chunks=(), media=media)
    assert exc_info.value.category == MediaRelationMaterializationFailureCategory.MISSING_SOURCE
