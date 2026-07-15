from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from knowledgenexus.foundation.domain.records import (
    ACLRecordBuilder,
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
    RelationRecordBuilder,
)
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules import (
    AclIdGenerator,
    ChunkIdGenerator,
    DocumentIdGenerator,
    RelationIdGenerator,
)
from knowledgenexus.foundation.infrastructure.exporters import (
    FullSnapshotPublisher,
    FullSnapshotStagingCompleter,
    FullSnapshotStagingWriter,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


GOLDEN_DATASET_VERSION = "v20260714-000000-000000Z"
GOLDEN_GENERATED_AT = "2026-07-14T00:00:00.000000Z"
GOLDEN_CONFIG_HASH = "a" * 64
GOLDEN_CHUNKER_VERSION = "1.2.0"
GOLDEN_SCHEMAS_VERSION = "1.0"

GOLDEN_PAGE_ID = "golden-page-001"
GOLDEN_DOCUMENT_ID = DocumentIdGenerator.confluence_page_id(GOLDEN_PAGE_ID)
GOLDEN_JIRA_KEY = "GOLDEN-1"
GOLDEN_JIRA_ID = f"jira:issue:{GOLDEN_JIRA_KEY}"
GOLDEN_RELATION_TYPE = "mentions_jira_key"
GOLDEN_RELATION_ID = RelationIdGenerator.generate_relation_id(
    GOLDEN_DOCUMENT_ID,
    GOLDEN_RELATION_TYPE,
    GOLDEN_JIRA_ID,
)
GOLDEN_ACL_ID = AclIdGenerator.generate_acl_id(GOLDEN_DOCUMENT_ID)
GOLDEN_ACL_TAGS = ["space:GOLDEN"]
GOLDEN_TITLE = "Golden Foundation Sample"
GOLDEN_PROSE_HEADING_PATH = [GOLDEN_TITLE, "Overview"]
GOLDEN_CODE_HEADING_PATH = [GOLDEN_TITLE, "Example Code"]
GOLDEN_PROSE_BREADCRUMB = " › ".join(GOLDEN_PROSE_HEADING_PATH)
GOLDEN_CODE_BREADCRUMB = " › ".join(GOLDEN_CODE_HEADING_PATH)
GOLDEN_PROSE_BODY = "Golden sample document for Foundation contract verification."
GOLDEN_CODE_BODY = "int golden_value() { return 42; }"
GOLDEN_FENCED_CODE_BODY = f"```cpp\n{GOLDEN_CODE_BODY}\n```"
GOLDEN_PROSE_TEXT = f"{GOLDEN_PROSE_BREADCRUMB}\n\n{GOLDEN_PROSE_BODY}"
GOLDEN_CODE_TEXT = f"{GOLDEN_CODE_BREADCRUMB}\n\n{GOLDEN_FENCED_CODE_BODY}"
GOLDEN_PROSE_TOKEN_COUNT = 13
GOLDEN_CODE_TOKEN_COUNT = 18
GOLDEN_PROSE_CHUNK_ID = ChunkIdGenerator.generate_chunk_id(
    "confluence",
    GOLDEN_DOCUMENT_ID,
    GOLDEN_PROSE_BREADCRUMB,
    GOLDEN_PROSE_TEXT,
)
GOLDEN_CODE_CHUNK_ID = ChunkIdGenerator.generate_chunk_id(
    "confluence",
    GOLDEN_DOCUMENT_ID,
    f"{GOLDEN_CODE_BREADCRUMB}#code0",
    GOLDEN_CODE_TEXT,
)
GOLDEN_MEDIA_ATTACHMENT_ID = "golden-media-001"
GOLDEN_MEDIA_ID = DocumentIdGenerator.confluence_attachment_id(
    GOLDEN_MEDIA_ATTACHMENT_ID
)
GOLDEN_SOURCE_SCOPES = {
    "confluence": {
        "space_keys": ["GOLDEN"],
        "page_ids": [GOLDEN_PAGE_ID],
    }
}


def build_golden_record_set() -> dict[str, list[dict[str, object]]]:
    document = _build_document_record()
    content_hash = document["content_hash"]
    assert isinstance(content_hash, str)

    return {
        "documents": [document],
        "chunks": [_build_prose_chunk_record(), _build_code_chunk_record()],
        "relations": [_build_relation_record()],
        "acl": [_build_acl_record()],
        "media_assets": [_build_media_asset_record()],
        "symbols": [],
        "sync_state": [_build_sync_state_record(content_hash)],
        "tombstones": [],
    }


def generate_golden_full_snapshot(dataset_root: Path) -> Path:
    records = build_golden_record_set()
    validator = FoundationSchemaValidator()
    staging_path = dataset_root / ".staging-golden"

    FullSnapshotStagingWriter.write(
        staging_path=staging_path,
        validator=validator,
        dataset_version=GOLDEN_DATASET_VERSION,
        generated_at=GOLDEN_GENERATED_AT,
        config_hash=GOLDEN_CONFIG_HASH,
        chunker_version=GOLDEN_CHUNKER_VERSION,
        schemas_version=GOLDEN_SCHEMAS_VERSION,
        documents=_one_pass(records["documents"]),
        chunks=_one_pass(records["chunks"]),
        relations=_one_pass(records["relations"]),
        acl=_one_pass(records["acl"]),
        media_assets=_one_pass(records["media_assets"]),
        symbols=_one_pass(records["symbols"]),
        sync_state=_one_pass(records["sync_state"]),
        tombstones=_one_pass(records["tombstones"]),
        source_scopes=GOLDEN_SOURCE_SCOPES,
    )
    FullSnapshotStagingCompleter.complete(
        staging_path=staging_path,
        validator=validator,
    )
    return FullSnapshotPublisher.publish(
        staging_path=staging_path,
        dataset_root=dataset_root,
        validator=validator,
    )


def _build_document_record() -> dict[str, object]:
    normalized_body_text = f"{GOLDEN_PROSE_BODY}\n\n{GOLDEN_FENCED_CODE_BODY}"
    return CanonicalDocumentRecordBuilder.build(
        document_id=GOLDEN_DOCUMENT_ID,
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=normalized_body_text,
        acl_id=GOLDEN_ACL_ID,
        crawled_at=GOLDEN_GENERATED_AT,
        title=GOLDEN_TITLE,
        space_key="GOLDEN",
        page_id=GOLDEN_PAGE_ID,
        url="https://example.invalid/golden/page-001",
        source_version="1",
        jira_keys=[GOLDEN_JIRA_KEY],
        relation_ids=[GOLDEN_RELATION_ID],
        updated_at=GOLDEN_GENERATED_AT,
        metadata={"fixture": "golden-full-snapshot"},
    )


def _build_prose_chunk_record() -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id=GOLDEN_PROSE_CHUNK_ID,
        document_id=GOLDEN_DOCUMENT_ID,
        source_system="confluence",
        source_type="wiki_page",
        text=GOLDEN_PROSE_TEXT,
        content_kind="prose",
        language="en",
        token_count=GOLDEN_PROSE_TOKEN_COUNT,
        acl_tags=GOLDEN_ACL_TAGS,
        chunker_version=GOLDEN_CHUNKER_VERSION,
        title=GOLDEN_TITLE,
        heading_path=GOLDEN_PROSE_HEADING_PATH,
        space_key="GOLDEN",
        page_id=GOLDEN_PAGE_ID,
        jira_keys=[GOLDEN_JIRA_KEY],
        relation_ids=[GOLDEN_RELATION_ID],
        source_version="1",
        updated_at=GOLDEN_GENERATED_AT,
    )


def _build_code_chunk_record() -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id=GOLDEN_CODE_CHUNK_ID,
        document_id=GOLDEN_DOCUMENT_ID,
        source_system="confluence",
        source_type="wiki_page",
        text=GOLDEN_CODE_TEXT,
        content_kind="code_block",
        language="cpp",
        token_count=GOLDEN_CODE_TOKEN_COUNT,
        acl_tags=GOLDEN_ACL_TAGS,
        chunker_version=GOLDEN_CHUNKER_VERSION,
        title=GOLDEN_TITLE,
        heading_path=GOLDEN_CODE_HEADING_PATH,
        space_key="GOLDEN",
        page_id=GOLDEN_PAGE_ID,
        jira_keys=[],
        relation_ids=[],
        source_version="1",
        updated_at=GOLDEN_GENERATED_AT,
    )


def _build_relation_record() -> dict[str, object]:
    return RelationRecordBuilder.build(
        relation_id=GOLDEN_RELATION_ID,
        source_id=GOLDEN_DOCUMENT_ID,
        target_id=GOLDEN_JIRA_ID,
        relation_type=GOLDEN_RELATION_TYPE,
        resolution_status="unresolved_without_jira_api",
        created_at=GOLDEN_GENERATED_AT,
        evidence=f"Synthetic reference to {GOLDEN_JIRA_KEY}.",
        confidence=1,
    )


def _build_acl_record() -> dict[str, object]:
    return ACLRecordBuilder.build(
        acl_id=GOLDEN_ACL_ID,
        document_id=GOLDEN_DOCUMENT_ID,
        source_system="confluence",
        is_restricted=False,
        acl_tags=GOLDEN_ACL_TAGS,
        acl_extraction_status="ok",
        extracted_at=GOLDEN_GENERATED_AT,
        crawler_identity="golden-fixture-crawler",
        acl_confidence="exact",
    )


def _build_media_asset_record() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "media_id": GOLDEN_MEDIA_ID,
        "parent_document_id": GOLDEN_DOCUMENT_ID,
        "source_system": "confluence",
        "filename": "golden-diagram.txt",
        "mime_type": "text/plain",
        "size_bytes": 42,
        "download_status": "downloaded",
        "processing_status": "parsed",
        "relevance": "high",
        "extracted_text": "Synthetic diagram text for contract verification.",
        "summary": "Synthetic golden media fixture.",
        "confidence": 1,
        "raw_uri": "raw://golden/media-001",
        "content_hash": "b" * 64,
        "source_version": "1",
        "updated_at": GOLDEN_GENERATED_AT,
        "crawled_at": GOLDEN_GENERATED_AT,
    }


def _build_sync_state_record(content_hash: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": "confluence_golden_fixture",
        "entity_id": GOLDEN_DOCUMENT_ID,
        "entity_type": "page",
        "last_seen_version": "1",
        "last_content_hash": content_hash,
        "last_synced_at": GOLDEN_GENERATED_AT,
        "status": "active",
    }


def _one_pass(records: list[dict[str, object]]) -> Iterator[dict[str, object]]:
    yield from records
