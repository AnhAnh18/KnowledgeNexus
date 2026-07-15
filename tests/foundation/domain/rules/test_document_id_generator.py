from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules import DocumentIdGenerator


def test_confluence_page_id_is_readable_and_deterministic() -> None:
    assert (
        DocumentIdGenerator.confluence_page_id("938880621")
        == "confluence:page:938880621"
    )


def test_confluence_attachment_id_is_readable_and_deterministic() -> None:
    assert (
        DocumentIdGenerator.confluence_attachment_id("123456")
        == "confluence:attachment:123456"
    )


def test_git_file_id_preserves_repo_and_file_path() -> None:
    assert (
        DocumentIdGenerator.git_file_id(
            "spen-sdk",
            "src/native/ObjectManager.cpp",
        )
        == "git:file:spen-sdk:src/native/ObjectManager.cpp"
    )


def test_same_inputs_produce_same_ids() -> None:
    assert DocumentIdGenerator.confluence_page_id(
        "938880621"
    ) == DocumentIdGenerator.confluence_page_id("938880621")
    assert DocumentIdGenerator.git_file_id(
        "spen-sdk",
        "src/native/ObjectManager.cpp",
    ) == DocumentIdGenerator.git_file_id(
        "spen-sdk",
        "src/native/ObjectManager.cpp",
    )


def test_different_page_id_changes_confluence_page_document_id() -> None:
    assert DocumentIdGenerator.confluence_page_id(
        "938880621"
    ) != DocumentIdGenerator.confluence_page_id("938880622")


def test_different_repo_changes_git_file_document_id() -> None:
    assert DocumentIdGenerator.git_file_id(
        "spen-sdk",
        "src/native/ObjectManager.cpp",
    ) != DocumentIdGenerator.git_file_id(
        "other-repo",
        "src/native/ObjectManager.cpp",
    )


def test_different_file_path_changes_git_file_document_id() -> None:
    assert DocumentIdGenerator.git_file_id(
        "spen-sdk",
        "src/native/ObjectManager.cpp",
    ) != DocumentIdGenerator.git_file_id(
        "spen-sdk",
        "src/native/Other.cpp",
    )


def test_git_file_id_preserves_file_path_exactly() -> None:
    file_path = " src/native/ObjectManager.cpp "

    assert (
        DocumentIdGenerator.git_file_id("spen-sdk", file_path)
        == f"git:file:spen-sdk:{file_path}"
    )


def test_source_entity_id_supports_single_stable_part() -> None:
    assert (
        DocumentIdGenerator.source_entity_id("jira", "issue", "SVMCSPEN-1234")
        == "jira:issue:SVMCSPEN-1234"
    )


def test_source_entity_id_supports_multiple_stable_parts() -> None:
    assert (
        DocumentIdGenerator.source_entity_id("github", "issue", "spen-sdk", "245")
        == "github:issue:spen-sdk:245"
    )


def test_source_entity_id_keeps_entity_kind_readable() -> None:
    assert (
        DocumentIdGenerator.source_entity_id(
            "github",
            "pull_request",
            "spen-sdk",
            "88",
        )
        == "github:pull_request:spen-sdk:88"
    )


def test_source_entity_id_requires_at_least_one_stable_part() -> None:
    with pytest.raises(ValueError, match="stable_parts must not be empty"):
        DocumentIdGenerator.source_entity_id("jira", "issue")


def test_source_entity_id_non_string_stable_part_fails() -> None:
    with pytest.raises(TypeError, match=r"stable_parts\[0\] expects str"):
        DocumentIdGenerator.source_entity_id(
            "jira",
            "issue",
            123,  # type: ignore[arg-type]
        )


def test_source_entity_id_empty_stable_part_fails() -> None:
    with pytest.raises(ValueError, match=r"stable_parts\[0\] must not be empty"):
        DocumentIdGenerator.source_entity_id("jira", "issue", "")


def test_source_entity_id_empty_later_stable_part_fails() -> None:
    with pytest.raises(ValueError, match=r"stable_parts\[1\] must not be empty"):
        DocumentIdGenerator.source_entity_id("github", "issue", "spen-sdk", "")


def test_non_string_input_fails() -> None:
    with pytest.raises(TypeError, match="page_id expects str"):
        DocumentIdGenerator.confluence_page_id(123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("method_name", "args", "field_name"),
    [
        ("confluence_page_id", ("",), "page_id"),
        ("confluence_attachment_id", ("",), "attachment_id"),
        ("git_file_id", ("", "src/native/ObjectManager.cpp"), "repo"),
        ("git_file_id", ("spen-sdk", ""), "file_path"),
    ],
)
def test_empty_string_input_fails(
    method_name: str,
    args: tuple[str, ...],
    field_name: str,
) -> None:
    method = getattr(DocumentIdGenerator, method_name)

    with pytest.raises(ValueError, match=f"{field_name} must not be empty"):
        method(*args)
