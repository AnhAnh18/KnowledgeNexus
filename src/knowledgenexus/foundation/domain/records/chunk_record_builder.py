from __future__ import annotations

from typing import Any

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.foundation.domain.rules import ContentHasher


class ChunkRecordBuilder:
    """Build plain ChunkRecord dicts shaped by the Foundation schema."""

    @classmethod
    def build(
        cls,
        *,
        chunk_id: str,
        document_id: str,
        source_system: str,
        source_type: str,
        text: str,
        content_kind: str,
        language: str,
        token_count: int,
        acl_tags: list[str],
        chunker_version: str,
        title: str | None = None,
        heading_path: list[str] | None = None,
        space_key: str | None = None,
        page_id: str | None = None,
        repo: str | None = None,
        branch: str | None = None,
        file_path: str | None = None,
        symbol: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        part_index: int | None = None,
        part_total: int | None = None,
        jira_keys: list[str] | None = None,
        relation_ids: list[str] | None = None,
        source_version: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, object]:
        cls._require_non_empty_string("chunk_id", chunk_id)
        cls._require_non_empty_string("document_id", document_id)
        cls._require_non_empty_string("source_system", source_system)
        cls._require_non_empty_string("source_type", source_type)
        cls._require_non_empty_string("text", text)
        cls._require_non_empty_string("content_kind", content_kind)
        cls._require_non_empty_string("language", language)
        cls._require_non_empty_string("chunker_version", chunker_version)
        cls._require_non_negative_int("token_count", token_count)
        cls._require_non_empty_list("acl_tags", acl_tags)

        for field_name, value in {
            "title": title,
            "space_key": space_key,
            "page_id": page_id,
            "repo": repo,
            "branch": branch,
            "file_path": file_path,
            "symbol": symbol,
            "source_version": source_version,
            "updated_at": updated_at,
        }.items():
            cls._require_optional_string(field_name, value)

        for field_name, value in {
            "line_start": line_start,
            "line_end": line_end,
            "part_index": part_index,
            "part_total": part_total,
        }.items():
            cls._require_optional_int(field_name, value)

        cls._require_optional_list("heading_path", heading_path)
        cls._require_optional_list("jira_keys", jira_keys)
        cls._require_optional_list("relation_ids", relation_ids)

        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "chunk_id": chunk_id,
            "document_id": document_id,
            "source_system": source_system,
            "source_type": source_type,
            "text": text,
            "content_kind": content_kind,
            "language": language,
            "token_count": token_count,
            "acl_tags": list(acl_tags),
            "content_hash": ContentHasher.hash_text(text),
            "chunker_version": chunker_version,
            "jira_keys": list(jira_keys or []),
            "relation_ids": list(relation_ids or []),
        }

        optional_fields: dict[str, object] = {
            "title": title,
            "heading_path": list(heading_path) if heading_path is not None else None,
            "space_key": space_key,
            "page_id": page_id,
            "repo": repo,
            "branch": branch,
            "file_path": file_path,
            "symbol": symbol,
            "line_start": line_start,
            "line_end": line_end,
            "part_index": part_index,
            "part_total": part_total,
            "source_version": source_version,
            "updated_at": updated_at,
        }
        record.update(
            {
                field_name: value
                for field_name, value in optional_fields.items()
                if value is not None
            }
        )

        return record

    @staticmethod
    def _require_string(field_name: str, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"ChunkRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_non_empty_string(field_name: str, value: Any) -> None:
        ChunkRecordBuilder._require_string(field_name, value)
        if value == "":
            raise ValueError(f"ChunkRecordBuilder.{field_name} must not be empty")

    @staticmethod
    def _require_optional_string(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, str):
            raise TypeError(f"ChunkRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_non_negative_int(field_name: str, value: Any) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"ChunkRecordBuilder.{field_name} expects int")
        if value < 0:
            raise ValueError(f"ChunkRecordBuilder.{field_name} must not be negative")

    @staticmethod
    def _require_optional_int(field_name: str, value: Any) -> None:
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise TypeError(f"ChunkRecordBuilder.{field_name} expects int")

    @staticmethod
    def _require_optional_list(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, list):
            raise TypeError(f"ChunkRecordBuilder.{field_name} expects list")

    @staticmethod
    def _require_non_empty_list(field_name: str, value: Any) -> None:
        if not isinstance(value, list):
            raise TypeError(f"ChunkRecordBuilder.{field_name} expects list")
        if not value:
            raise ValueError(f"ChunkRecordBuilder.{field_name} must not be empty")
