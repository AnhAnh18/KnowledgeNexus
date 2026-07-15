from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION


class ManifestRecordBuilder:
    """Build plain Manifest dicts shaped by the Foundation schema."""

    @classmethod
    def build(
        cls,
        *,
        dataset_version: str,
        export_mode: str,
        generated_at: str,
        config_hash: str,
        chunker_version: str,
        schemas_version: str,
        counts: Mapping[str, int],
        base_dataset_version: str | None = None,
        source_scopes: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        cls._require_non_empty_string("dataset_version", dataset_version)
        cls._require_non_empty_string("export_mode", export_mode)
        cls._require_non_empty_string("generated_at", generated_at)
        cls._require_non_empty_string("config_hash", config_hash)
        cls._require_non_empty_string("chunker_version", chunker_version)
        cls._require_non_empty_string("schemas_version", schemas_version)
        cls._require_optional_string("base_dataset_version", base_dataset_version)

        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "dataset_version": dataset_version,
            "export_mode": export_mode,
            "generated_at": generated_at,
            "config_hash": config_hash,
            "chunker_version": chunker_version,
            "schemas_version": schemas_version,
            "counts": cls._copy_counts(counts),
        }

        if base_dataset_version is not None:
            record["base_dataset_version"] = base_dataset_version

        if source_scopes is not None:
            record["source_scopes"] = cls._copy_source_scopes(source_scopes)

        return record

    @staticmethod
    def _require_string(field_name: str, value: Any) -> None:
        if not isinstance(value, str):
            raise TypeError(f"ManifestRecordBuilder.{field_name} expects str")

    @staticmethod
    def _require_non_empty_string(field_name: str, value: Any) -> None:
        ManifestRecordBuilder._require_string(field_name, value)
        if value == "":
            raise ValueError(
                f"ManifestRecordBuilder.{field_name} must not be empty"
            )

    @staticmethod
    def _require_optional_string(field_name: str, value: Any) -> None:
        if value is not None and not isinstance(value, str):
            raise TypeError(f"ManifestRecordBuilder.{field_name} expects str")

    @staticmethod
    def _copy_counts(counts: Mapping[str, int]) -> dict[str, int]:
        if not isinstance(counts, Mapping):
            raise TypeError("ManifestRecordBuilder.counts expects Mapping")

        copied_counts: dict[str, int] = {}
        for key, value in counts.items():
            if not isinstance(key, str):
                raise TypeError("ManifestRecordBuilder.counts keys must be strings")
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "ManifestRecordBuilder.counts values must be integers"
                )
            if value < 0:
                raise ValueError(
                    "ManifestRecordBuilder.counts values must be non-negative"
                )
            copied_counts[key] = value

        return copied_counts

    @staticmethod
    def _copy_source_scopes(
        source_scopes: Mapping[str, object],
    ) -> dict[str, object]:
        if not isinstance(source_scopes, Mapping):
            raise TypeError("ManifestRecordBuilder.source_scopes expects Mapping")

        for key in source_scopes:
            if not isinstance(key, str):
                raise TypeError(
                    "ManifestRecordBuilder.source_scopes keys must be strings"
                )

        return copy.deepcopy(dict(source_scopes))
