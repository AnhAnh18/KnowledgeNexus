from __future__ import annotations

from typing import Any

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION


class ACLRecordBuilder:
    """Build plain ACLRecord dicts shaped by the Foundation schema."""

    @classmethod
    def build(
        cls,
        *,
        acl_id: str,
        document_id: str,
        source_system: str,
        is_restricted: bool,
        acl_tags: list[str],
        acl_extraction_status: str,
        extracted_at: str,
        crawler_identity: str | None = None,
        restriction_inherited: bool | None = None,
        restriction_source_page_ids: list[str] | None = None,
        allowed_users: list[str] | None = None,
        allowed_groups: list[str] | None = None,
        acl_confidence: str | None = None,
    ) -> dict[str, object]:
        cls._require_non_empty_string("acl_id", acl_id)
        cls._require_non_empty_string("document_id", document_id)
        cls._require_non_empty_string("source_system", source_system)
        cls._require_bool("is_restricted", is_restricted)
        cls._require_non_empty_list("acl_tags", acl_tags)
        cls._require_non_empty_string("acl_extraction_status", acl_extraction_status)
        cls._require_non_empty_string("extracted_at", extracted_at)

        cls._require_optional_string("crawler_identity", crawler_identity)
        cls._require_optional_string("acl_confidence", acl_confidence)
        cls._require_optional_bool("restriction_inherited", restriction_inherited)
        cls._require_optional_list(
            "restriction_source_page_ids",
            restriction_source_page_ids,
        )
        cls._require_optional_list("allowed_users", allowed_users)
        cls._require_optional_list("allowed_groups", allowed_groups)

        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "acl_id": acl_id,
            "document_id": document_id,
            "source_system": source_system,
            "is_restricted": is_restricted,
            "acl_tags": list(acl_tags),
            "acl_extraction_status": acl_extraction_status,
            "extracted_at": extracted_at,
        }

        optional_fields: dict[str, object] = {
            "crawler_identity": crawler_identity,
            "restriction_inherited": restriction_inherited,
            "restriction_source_page_ids": (
                list(restriction_source_page_ids)
                if restriction_source_page_ids is not None
                else None
            ),
            "allowed_users": list(allowed_users)
            if allowed_users is not None
            else None,
            "allowed_groups": list(allowed_groups)
            if allowed_groups is not None
            else None,
            "acl_confidence": acl_confidence,
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
            raise TypeError(f"ACLRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_non_empty_string(field_name: str, value: Any) -> None:
        ACLRecordBuilder._require_string(field_name, value)
        if value == "":
            raise ValueError(f"ACLRecordBuilder.{field_name} must not be empty")

    @staticmethod
    def _require_optional_string(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, str):
            raise TypeError(f"ACLRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_bool(field_name: str, value: Any) -> None:
        if not isinstance(value, bool):
            raise TypeError(f"ACLRecordBuilder.{field_name} expects bool")

    @staticmethod
    def _require_optional_bool(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, bool):
            raise TypeError(f"ACLRecordBuilder.{field_name} expects bool")

    @staticmethod
    def _require_optional_list(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, list):
            raise TypeError(f"ACLRecordBuilder.{field_name} expects list")

    @staticmethod
    def _require_non_empty_list(field_name: str, value: Any) -> None:
        if not isinstance(value, list):
            raise TypeError(f"ACLRecordBuilder.{field_name} expects list")
        if not value:
            raise ValueError(f"ACLRecordBuilder.{field_name} must not be empty")
