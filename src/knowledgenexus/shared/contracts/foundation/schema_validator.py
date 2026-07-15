"""Shared Foundation JSON Schema validation utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from knowledgenexus.shared.contracts.foundation.contract_loader import (
    FoundationContractSchemas,
    load_foundation_contract_schemas,
)

try:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError:  # pragma: no cover - compatibility path for older jsonschema
    Registry = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    DRAFT202012 = None  # type: ignore[assignment]


_FORMAT_CHECKER = FormatChecker()


@dataclass(frozen=True)
class FoundationValidationError(ValueError):
    """Validation failure with enough context for export/import diagnostics."""

    schema_name: str
    message: str
    error_path: str = "<root>"
    file_path: Path | None = None
    line_number: int | None = None

    def __str__(self) -> str:
        location = ""
        if self.file_path is not None:
            location = f" in {self.file_path}"
        if self.line_number is not None:
            location = f"{location} at line {self.line_number}"

        return (
            f"Foundation schema validation failed for '{self.schema_name}'{location}: "
            f"{self.message} (path: {self.error_path})"
        )


class FoundationSchemaValidator:
    """Validate Foundation records against schemas loaded from ``contracts/foundation``."""

    def __init__(self, contract_schemas: FoundationContractSchemas | None = None) -> None:
        self.contract_schemas = contract_schemas or load_foundation_contract_schemas()

    @classmethod
    def from_contract_root(cls, contract_root: str | Path) -> "FoundationSchemaValidator":
        return cls(load_foundation_contract_schemas(contract_root=contract_root))

    @classmethod
    def from_schema_dir(cls, schema_dir: str | Path) -> "FoundationSchemaValidator":
        return cls(load_foundation_contract_schemas(schema_dir=schema_dir))

    def validate_record(
        self,
        schema_name: str,
        record: Mapping[str, Any],
        *,
        file_path: str | Path | None = None,
        line_number: int | None = None,
    ) -> None:
        """Validate one Python mapping without mutating it."""

        schema = self.contract_schemas.get_schema(schema_name)
        validator = self._validator_for(schema)

        errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            raise self._to_validation_error(
                schema_name,
                errors[0],
                file_path=Path(file_path) if file_path is not None else None,
                line_number=line_number,
            )

    def validate_jsonl_file(self, schema_name: str, file_path: str | Path) -> int:
        """Validate a JSONL file line-by-line.

        Returns the number of records validated. Blank or malformed lines are
        invalid JSON and fail with their line number.
        """

        resolved_path = Path(file_path)
        count = 0

        with resolved_path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise FoundationValidationError(
                        schema_name=schema_name,
                        message=f"Invalid JSON: {exc.msg}",
                        error_path="<json>",
                        file_path=resolved_path,
                        line_number=line_number,
                    ) from exc

                if not isinstance(record, dict):
                    raise FoundationValidationError(
                        schema_name=schema_name,
                        message="JSONL record must be an object",
                        error_path="<root>",
                        file_path=resolved_path,
                        line_number=line_number,
                    )

                self.validate_record(
                    schema_name,
                    record,
                    file_path=resolved_path,
                    line_number=line_number,
                )
                count += 1

        return count

    def _validator_for(self, schema: Mapping[str, Any]) -> Draft202012Validator:
        if Registry is not None and Resource is not None:
            registry = Registry().with_resources(
                (
                    schema_id,
                    Resource.from_contents(
                        schema_doc,
                        default_specification=DRAFT202012,
                    ),
                )
                for schema_id, schema_doc in self.contract_schemas.schemas_by_id.items()
            )
            return Draft202012Validator(
                schema,
                registry=registry,
                format_checker=_FORMAT_CHECKER,
            )

        from jsonschema import RefResolver

        resolver = RefResolver.from_schema(
            schema,
            store=dict(self.contract_schemas.schemas_by_id),
        )
        return Draft202012Validator(
            schema,
            resolver=resolver,
            format_checker=_FORMAT_CHECKER,
        )

    @staticmethod
    def _to_validation_error(
        schema_name: str,
        error: ValidationError,
        *,
        file_path: Path | None,
        line_number: int | None,
    ) -> FoundationValidationError:
        error_path = _format_error_path(error)
        return FoundationValidationError(
            schema_name=schema_name,
            message=error.message,
            error_path=error_path,
            file_path=file_path,
            line_number=line_number,
        )


def validate_record(schema_name: str, record: Mapping[str, Any]) -> None:
    """Validate one record using the default Foundation contract root."""

    FoundationSchemaValidator().validate_record(schema_name, record)


def validate_jsonl_file(schema_name: str, file_path: str | Path) -> int:
    """Validate a JSONL file using the default Foundation contract root."""

    return FoundationSchemaValidator().validate_jsonl_file(schema_name, file_path)


def _format_error_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "<root>"

    parts: list[str] = []
    for item in error.absolute_path:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            separator = "." if parts else ""
            parts.append(f"{separator}{item}")

    return "".join(parts)
