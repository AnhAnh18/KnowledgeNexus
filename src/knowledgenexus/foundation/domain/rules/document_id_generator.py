from __future__ import annotations


class DocumentIdGenerator:
    """Readable deterministic document ID helpers for Foundation source documents."""

    @classmethod
    def source_entity_id(
        cls,
        source_system: str,
        entity_kind: str,
        *stable_parts: str,
    ) -> str:
        cls._require_non_empty_string("source_system", source_system)
        cls._require_non_empty_string("entity_kind", entity_kind)
        if not stable_parts:
            raise ValueError("DocumentIdGenerator.stable_parts must not be empty")

        for index, stable_part in enumerate(stable_parts):
            cls._require_non_empty_string(f"stable_parts[{index}]", stable_part)

        return ":".join([source_system, entity_kind, *stable_parts])

    @classmethod
    def confluence_page_id(cls, page_id: str) -> str:
        cls._require_non_empty_string("page_id", page_id)
        return cls.source_entity_id("confluence", "page", page_id)

    @classmethod
    def confluence_attachment_id(cls, attachment_id: str) -> str:
        cls._require_non_empty_string("attachment_id", attachment_id)
        return cls.source_entity_id("confluence", "attachment", attachment_id)

    @classmethod
    def git_file_id(cls, repo: str, file_path: str) -> str:
        cls._require_non_empty_string("repo", repo)
        cls._require_non_empty_string("file_path", file_path)
        return cls.source_entity_id("git", "file", repo, file_path)

    @staticmethod
    def _require_non_empty_string(field_name: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"DocumentIdGenerator.{field_name} expects str")
        if value == "":
            raise ValueError(f"DocumentIdGenerator.{field_name} must not be empty")
