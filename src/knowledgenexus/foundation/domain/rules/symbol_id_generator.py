from __future__ import annotations

import hashlib


class SymbolIdGenerator:
    """Generate stable branch-bound symbol identities."""

    @classmethod
    def generate(
        cls,
        *,
        repo: str,
        branch: str,
        file_path: str,
        qualified_name: str,
        signature: str | None = None,
        overloaded: bool = False,
    ) -> str:
        values = (repo, branch, file_path, qualified_name)
        if any(type(value) is not str or not value for value in values):
            raise TypeError("symbol identity fields are invalid")
        if type(overloaded) is not bool:
            raise TypeError("overloaded is invalid")
        if overloaded:
            if type(signature) is not str or not signature:
                raise ValueError("overload signature is invalid")
            suffix = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:8]
            qualified_name = f"{qualified_name}~{suffix}"
        elif signature is not None and type(signature) is not str:
            raise TypeError("signature is invalid")
        return f"{repo}:{branch}:{file_path}:{qualified_name}"


__all__ = ["SymbolIdGenerator"]
