from __future__ import annotations


class AclIdGenerator:
    """Deterministic ACL ID generation from a Foundation document ID."""

    @staticmethod
    def generate_acl_id(document_id: str) -> str:
        if not isinstance(document_id, str):
            raise TypeError("AclIdGenerator.document_id expects str")
        if document_id == "":
            raise ValueError("AclIdGenerator.document_id must not be empty")

        return f"acl:{document_id}"
