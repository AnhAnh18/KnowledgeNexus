"""Application boundary for the pure M10 in-memory composition gate."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from knowledgenexus.foundation.domain.models.m10_composition import (
    M10ConfluenceAdapter,
    M10ConfluenceHandoff,
    M10GitAdapter,
    M10GitHandoff,
    M10SchemaValidator,
    _require_canonical_validator,
    compose_m10_projection,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotError, M10SnapshotProjection, M10SnapshotRequest


class M10CompositionFailureCategory(StrEnum):
    INVALID_REQUEST = "invalid_request"
    ADAPTER = "adapter"
    PROJECTION = "projection"


class M10CompositionFailure(Exception):
    """Sanitized failure; adapter exception text and source data never escape."""

    def __init__(self, category: M10CompositionFailureCategory):
        if type(category) is not M10CompositionFailureCategory:
            raise TypeError("category is invalid")
        self.category = category
        super().__init__(category.value)


@dataclass(frozen=True)
class M10CompositionResult:
    projection: M10SnapshotProjection | None
    failure_category: M10CompositionFailureCategory | None = None

    def __post_init__(self) -> None:
        if type(self) is not M10CompositionResult or set(vars(self)) != {"projection", "failure_category"}:
            raise TypeError("result has invalid fields")
        if self.projection is None and self.failure_category is None:
            raise ValueError("result must contain projection or failure")
        if self.projection is not None and type(self.projection) is not M10SnapshotProjection:
            raise TypeError("projection is invalid")
        if self.projection is not None and self.failure_category is not None:
            raise ValueError("result cannot contain both output and failure")
        if self.projection is None and type(self.failure_category) is not M10CompositionFailureCategory:
            raise ValueError("failure category is invalid")


class ComposeM10Snapshot:
    """Collects two injected handoffs, then composes them without side effects."""

    def __init__(self, *, confluence_adapter: M10ConfluenceAdapter, git_adapter: M10GitAdapter, schema_validator: M10SchemaValidator | None = None, canonical_schema_validator: M10SchemaValidator | None = None) -> None:
        try:
            if not callable(getattr(confluence_adapter, "collect", None)) or not callable(getattr(git_adapter, "collect", None)):
                raise ValueError("adapters must provide collect")
            if canonical_schema_validator is None:
                from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
                canonical_schema_validator = FoundationSchemaValidator()
            canonical_schema_validator = _require_canonical_validator(canonical_schema_validator)
            if schema_validator is None:
                schema_validator = canonical_schema_validator
            if not callable(getattr(schema_validator, "validate_record", None)) or not callable(getattr(canonical_schema_validator, "validate_record", None)):
                raise ValueError("schema validator is invalid")
        except Exception:
            raise M10CompositionFailure(M10CompositionFailureCategory.ADAPTER) from None
        self._confluence = confluence_adapter
        self._git = git_adapter
        self._validator = schema_validator
        self._canonical_validator = canonical_schema_validator

    def execute(self, request: object) -> M10CompositionResult:
        if type(request) is not M10SnapshotRequest:
            raise M10CompositionFailure(M10CompositionFailureCategory.INVALID_REQUEST)
        try:
            M10SnapshotRequest.__post_init__(request)
        except Exception:
            raise M10CompositionFailure(M10CompositionFailureCategory.INVALID_REQUEST) from None
        try:
            confluence = self._confluence.collect(request)
            git = self._git.collect(request)
        except Exception:
            raise M10CompositionFailure(M10CompositionFailureCategory.ADAPTER) from None
        if type(confluence) is not M10ConfluenceHandoff or type(git) is not M10GitHandoff:
            raise M10CompositionFailure(M10CompositionFailureCategory.ADAPTER)
        try:
            return M10CompositionResult(compose_m10_projection(request, confluence, git, schema_validator=self._validator, canonical_schema_validator=self._canonical_validator))
        except Exception:
            raise M10CompositionFailure(M10CompositionFailureCategory.PROJECTION) from None


__all__ = ["ComposeM10Snapshot", "M10CompositionFailure", "M10CompositionFailureCategory", "M10CompositionResult"]
