"""Shared Foundation JSON Schema validation utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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

try:
    from rfc3339_validator import validate_rfc3339
except ImportError:  # pragma: no cover - optional jsonschema format dependency
    validate_rfc3339 = None


_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time", raises=ValueError)
def _is_date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True

    if validate_rfc3339 is not None:
        return bool(validate_rfc3339(value.upper()))

    return _is_rfc3339_date_time(value)


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


def _is_rfc3339_date_time(value: str) -> bool:
    if value.count("T") != 1:
        return False

    date_part, time_part = value.split("T", maxsplit=1)
    if not _has_rfc3339_date_shape(date_part):
        return False
    if not _has_rfc3339_time_shape(time_part):
        return False

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False

    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _has_rfc3339_date_shape(value: str) -> bool:
    return (
        len(value) == 10
        and value[4] == "-"
        and value[7] == "-"
        and _all_digits(value[:4], value[5:7], value[8:10])
    )


def _has_rfc3339_time_shape(value: str) -> bool:
    time_value, offset_value = _split_rfc3339_offset(value)
    if offset_value is None:
        return False

    second_part, dot, fraction_part = time_value.partition(".")
    if dot and not fraction_part.isdigit():
        return False

    return (
        len(second_part) == 8
        and second_part[2] == ":"
        and second_part[5] == ":"
        and _all_digits(second_part[:2], second_part[3:5], second_part[6:8])
    )


def _split_rfc3339_offset(value: str) -> tuple[str, str | None]:
    if value.endswith("Z"):
        return value[:-1], "Z"

    for marker in ("+", "-"):
        marker_index = value.rfind(marker)
        if marker_index == -1:
            continue

        time_value = value[:marker_index]
        offset_value = value[marker_index:]
        if _has_rfc3339_offset_shape(offset_value):
            return time_value, offset_value

    return value, None


def _has_rfc3339_offset_shape(value: str) -> bool:
    return (
        len(value) == 6
        and value[0] in {"+", "-"}
        and value[3] == ":"
        and _all_digits(value[1:3], value[4:6])
    )


def _all_digits(*parts: str) -> bool:
    return all(part.isdigit() for part in parts)
