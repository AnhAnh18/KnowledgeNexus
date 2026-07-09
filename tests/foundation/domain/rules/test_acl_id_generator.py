from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules import AclIdGenerator


def test_same_document_id_produces_same_acl_id() -> None:
    document_id = "confluence:page:938880621"

    assert AclIdGenerator.generate_acl_id(document_id) == AclIdGenerator.generate_acl_id(
        document_id
    )


def test_confluence_document_id_is_prefixed_without_hashing() -> None:
    assert (
        AclIdGenerator.generate_acl_id("confluence:page:938880621")
        == "acl:confluence:page:938880621"
    )


def test_git_document_id_keeps_original_document_id_suffix() -> None:
    document_id = "git:repo:KnowledgeNexus:path:src/app.py"

    assert AclIdGenerator.generate_acl_id(document_id) == f"acl:{document_id}"


def test_non_string_input_fails() -> None:
    with pytest.raises(TypeError, match="document_id expects str"):
        AclIdGenerator.generate_acl_id(123)  # type: ignore[arg-type]


def test_empty_string_input_fails() -> None:
    with pytest.raises(ValueError, match="document_id must not be empty"):
        AclIdGenerator.generate_acl_id("")


def test_whitespace_only_string_is_kept_consistent_with_existing_generators() -> None:
    assert AclIdGenerator.generate_acl_id("   ") == "acl:   "
