from __future__ import annotations

from typing import Any

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules import ContentHasher


class CanonicalDocumentRecordBuilder:
    """Build plain CanonicalDocument record dicts shaped by the Foundation schema."""

    @classmethod
    def build(
        cls,
        *,
        document_id: str,
        source_system: str,
        source_type: str,
        normalized_body_text: str,
        acl_id: str,
        crawled_at: str,
        title: str | None = None,
        space_key: str | None = None,
        page_id: str | None = None,
        repo: str | None = None,
        branch: str | None = None,
        file_path: str | None = None,
        url: str | None = None,
        author: str | None = None,
        source_version: str | None = None,
        jira_keys: list[str] | None = None,
        relation_ids: list[str] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        cls._require_non_empty_string("document_id", document_id)
        cls._require_non_empty_string("source_system", source_system)
        cls._require_non_empty_string("source_type", source_type)
        cls._require_string("normalized_body_text", normalized_body_text)
        cls._require_non_empty_string("acl_id", acl_id)
        cls._require_non_empty_string("crawled_at", crawled_at)

        for field_name, value in {
            "title": title,
            "space_key": space_key,
            "page_id": page_id,
            "repo": repo,
            "branch": branch,
            "file_path": file_path,
            "url": url,
            "author": author,
            "source_version": source_version,
            "created_at": created_at,
            "updated_at": updated_at,
        }.items():
            cls._require_optional_string(field_name, value)

        if jira_keys is not None and not isinstance(jira_keys, list):
            raise TypeError("CanonicalDocumentRecordBuilder.jira_keys expects list")
        if relation_ids is not None and not isinstance(relation_ids, list):
            raise TypeError("CanonicalDocumentRecordBuilder.relation_ids expects list")
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("CanonicalDocumentRecordBuilder.metadata expects dict")

        return {
            "schema_version": SCHEMA_VERSION,
            "document_id": document_id,
            "source_system": source_system,
            "source_type": source_type,
            "title": title,
            "space_key": space_key,
            "page_id": page_id,
            "repo": repo,
            "branch": branch,
            "file_path": file_path,
            "url": url,
            "author": author,
            "source_version": source_version,
            "content_hash": ContentHasher.hash_text(normalized_body_text),
            "acl_id": acl_id,
            "jira_keys": list(jira_keys or []),
            "relation_ids": list(relation_ids or []),
            "created_at": created_at,
            "updated_at": updated_at,
            "crawled_at": crawled_at,
            "metadata": dict(metadata or {}),
        }

    @staticmethod
    def _require_string(field_name: str, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"CanonicalDocumentRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_non_empty_string(field_name: str, value: Any) -> None:
        CanonicalDocumentRecordBuilder._require_string(field_name, value)
        if value == "":
            raise ValueError(
                f"CanonicalDocumentRecordBuilder.{field_name} must not be empty"
            )

    @staticmethod
    def _require_optional_string(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, str):
            raise TypeError(f"CanonicalDocumentRecordBuilder.{field_name} expects str")
