from __future__ import annotations

from knowledgenexus.foundation.domain.records import (
    ACLRecordBuilder,
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
    RelationRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import (
    AclIdGenerator,
    ChunkIdGenerator,
    RelationIdGenerator,
)


DOCUMENT_ID = "confluence:page:123"
DOCUMENT_TITLE = "SVMC Sample Page"
JIRA_ISSUE_ID = "jira:issue:SPEN-1234"
JIRA_KEY = "SPEN-1234"
RELATION_TYPE = "mentions_jira_key"
SOURCE_SYSTEM = "confluence"
SOURCE_TYPE = "wiki_page"
SPACE_KEY = "SVMC"
TIMESTAMP = "2026-07-10T00:00:00Z"
NORMALIZED_BODY_TEXT = "SVMC Sample Page\n\nThis page mentions SPEN-1234."
CHUNK_TEXT = "This page mentions SPEN-1234."
CHUNKER_VERSION = "1.0.0"
ACL_TAGS = ["space:SVMC"]


def sample_relation_id() -> str:
    return RelationIdGenerator.generate_relation_id(
        DOCUMENT_ID,
        RELATION_TYPE,
        JIRA_ISSUE_ID,
    )


def sample_acl_id() -> str:
    return AclIdGenerator.generate_acl_id(DOCUMENT_ID)


def sample_chunk_id() -> str:
    return ChunkIdGenerator.generate_chunk_id(
        SOURCE_SYSTEM,
        DOCUMENT_ID,
        "body:0",
        CHUNK_TEXT,
    )


def build_sample_relation_record() -> dict[str, object]:
    return RelationRecordBuilder.build(
        relation_id=sample_relation_id(),
        source_id=DOCUMENT_ID,
        target_id=JIRA_ISSUE_ID,
        relation_type=RELATION_TYPE,
        resolution_status="unresolved_without_jira_api",
        created_at=TIMESTAMP,
        evidence="SPEN-1234 appears in the sample page body.",
        confidence=1,
    )


def build_sample_document_record() -> dict[str, object]:
    return CanonicalDocumentRecordBuilder.build(
        document_id=DOCUMENT_ID,
        source_system=SOURCE_SYSTEM,
        source_type=SOURCE_TYPE,
        normalized_body_text=NORMALIZED_BODY_TEXT,
        acl_id=sample_acl_id(),
        crawled_at=TIMESTAMP,
        title=DOCUMENT_TITLE,
        space_key=SPACE_KEY,
        page_id="123",
        url="https://confluence.example/pages/123",
        source_version="1",
        jira_keys=[JIRA_KEY],
        relation_ids=[sample_relation_id()],
        updated_at=TIMESTAMP,
        metadata={"fixture": "m2d-sample"},
    )


def build_sample_chunk_record() -> dict[str, object]:
    return ChunkRecordBuilder.build(
        chunk_id=sample_chunk_id(),
        document_id=DOCUMENT_ID,
        source_system=SOURCE_SYSTEM,
        source_type=SOURCE_TYPE,
        text=CHUNK_TEXT,
        content_kind="prose",
        language="en",
        token_count=5,
        acl_tags=ACL_TAGS,
        chunker_version=CHUNKER_VERSION,
        title=DOCUMENT_TITLE,
        heading_path=[DOCUMENT_TITLE],
        space_key=SPACE_KEY,
        page_id="123",
        jira_keys=[JIRA_KEY],
        relation_ids=[sample_relation_id()],
        source_version="1",
        updated_at=TIMESTAMP,
    )


def build_sample_acl_record() -> dict[str, object]:
    return ACLRecordBuilder.build(
        acl_id=sample_acl_id(),
        document_id=DOCUMENT_ID,
        source_system=SOURCE_SYSTEM,
        is_restricted=False,
        acl_tags=ACL_TAGS,
        acl_extraction_status="ok",
        extracted_at=TIMESTAMP,
        crawler_identity="fixture-crawler",
        acl_confidence="exact",
    )
