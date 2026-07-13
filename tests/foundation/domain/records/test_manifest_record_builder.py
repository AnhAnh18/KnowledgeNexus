from __future__ import annotations

from types import MappingProxyType

import pytest

from knowledgenexus.foundation.domain.records import ManifestRecordBuilder
from knowledgenexus.foundation.domain.records.common_constants import SCHEMA_VERSION
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
    FoundationValidationError,
)


VALID_DATASET_VERSION = "v20260713-093015-123456Z"
VALID_BASE_DATASET_VERSION = "v20260712-093015-123456Z"
VALID_GENERATED_AT = "2026-07-13T09:30:15.123456Z"
VALID_CONFIG_HASH = "a" * 64
VALID_CHUNKER_VERSION = "1.2.0"
VALID_SCHEMAS_VERSION = "1.0"


def build_minimal_full_snapshot_manifest(
    *,
    counts: dict[str, int] | None = None,
) -> dict[str, object]:
    return ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="full_snapshot",
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts=counts if counts is not None else {"documents": 1, "chunks": 2},
    )


def test_builder_returns_dict() -> None:
    assert isinstance(build_minimal_full_snapshot_manifest(), dict)


def test_record_has_schema_version_1_0() -> None:
    assert build_minimal_full_snapshot_manifest()["schema_version"] == SCHEMA_VERSION


def test_minimal_full_snapshot_manifest_passes_schema_validation() -> None:
    record = build_minimal_full_snapshot_manifest()

    assert "base_dataset_version" not in record
    assert "source_scopes" not in record
    FoundationSchemaValidator().validate_record("Manifest", record)


def test_full_manifest_with_source_scopes_passes_schema_validation() -> None:
    record = ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="full_snapshot",
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts={
            "documents": 1,
            "chunks": 2,
            "relations": 1,
            "acl": 1,
        },
        source_scopes={
            "confluence": {
                "space_keys": ["SVMC"],
                "page_ids": ["938880621"],
            },
            "git": {
                "repos": ["spen-sdk"],
                "branches": ["main"],
            },
        },
    )

    FoundationSchemaValidator().validate_record("Manifest", record)


def test_delta_shaped_manifest_preserves_base_dataset_version() -> None:
    record = ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="delta",
        base_dataset_version=VALID_BASE_DATASET_VERSION,
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts={"chunks": 1, "tombstones": 1},
    )

    assert record["base_dataset_version"] == VALID_BASE_DATASET_VERSION
    FoundationSchemaValidator().validate_record("Manifest", record)


def test_optional_fields_are_omitted_when_none() -> None:
    record = ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="full_snapshot",
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts={"documents": 1},
        base_dataset_version=None,
        source_scopes=None,
    )

    assert "base_dataset_version" not in record
    assert "source_scopes" not in record


def test_explicit_empty_source_scopes_is_preserved() -> None:
    record = build_minimal_full_snapshot_manifest()
    record_with_empty_source_scopes = ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="full_snapshot",
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts={"documents": 1},
        source_scopes={},
    )

    assert "source_scopes" not in record
    assert record_with_empty_source_scopes["source_scopes"] == {}
    FoundationSchemaValidator().validate_record(
        "Manifest",
        record_with_empty_source_scopes,
    )


def test_empty_counts_is_preserved_and_schema_valid() -> None:
    record = build_minimal_full_snapshot_manifest(counts={})

    assert record["counts"] == {}
    FoundationSchemaValidator().validate_record("Manifest", record)


@pytest.mark.parametrize("value", [0, 1, 42])
def test_zero_and_positive_count_values_are_accepted(value: int) -> None:
    record = build_minimal_full_snapshot_manifest(counts={"records": value})

    assert record["counts"] == {"records": value}
    FoundationSchemaValidator().validate_record("Manifest", record)


@pytest.mark.parametrize("value", [-1, -42])
def test_negative_count_values_fail(value: int) -> None:
    with pytest.raises(ValueError, match="counts values must be non-negative"):
        build_minimal_full_snapshot_manifest(counts={"records": value})


@pytest.mark.parametrize("value", [1.5, "1", True, False])
def test_non_integer_count_values_fail(value: object) -> None:
    with pytest.raises(TypeError, match="counts values must be integers"):
        ManifestRecordBuilder.build(
            dataset_version=VALID_DATASET_VERSION,
            export_mode="full_snapshot",
            generated_at=VALID_GENERATED_AT,
            config_hash=VALID_CONFIG_HASH,
            chunker_version=VALID_CHUNKER_VERSION,
            schemas_version=VALID_SCHEMAS_VERSION,
            counts={"records": value},  # type: ignore[dict-item]
        )


def test_non_string_count_keys_fail() -> None:
    with pytest.raises(TypeError, match="counts keys must be strings"):
        ManifestRecordBuilder.build(
            dataset_version=VALID_DATASET_VERSION,
            export_mode="full_snapshot",
            generated_at=VALID_GENERATED_AT,
            config_hash=VALID_CONFIG_HASH,
            chunker_version=VALID_CHUNKER_VERSION,
            schemas_version=VALID_SCHEMAS_VERSION,
            counts={1: 1},  # type: ignore[dict-item]
        )


def test_non_mapping_counts_fails() -> None:
    with pytest.raises(TypeError, match="counts expects Mapping"):
        ManifestRecordBuilder.build(
            dataset_version=VALID_DATASET_VERSION,
            export_mode="full_snapshot",
            generated_at=VALID_GENERATED_AT,
            config_hash=VALID_CONFIG_HASH,
            chunker_version=VALID_CHUNKER_VERSION,
            schemas_version=VALID_SCHEMAS_VERSION,
            counts=[("documents", 1)],  # type: ignore[arg-type]
        )


def test_generic_mapping_inputs_are_accepted_and_materialized() -> None:
    counts = MappingProxyType({"documents": 1})
    source_scopes = MappingProxyType(
        {
            "confluence": {
                "space_keys": ["SVMC"],
            }
        }
    )

    record = ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="full_snapshot",
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts=counts,
        source_scopes=source_scopes,
    )

    assert record["counts"] == {"documents": 1}
    assert type(record["counts"]) is dict
    assert record["source_scopes"] == {"confluence": {"space_keys": ["SVMC"]}}
    assert type(record["source_scopes"]) is dict


def test_non_mapping_source_scopes_fails() -> None:
    with pytest.raises(TypeError, match="source_scopes expects Mapping"):
        ManifestRecordBuilder.build(
            dataset_version=VALID_DATASET_VERSION,
            export_mode="full_snapshot",
            generated_at=VALID_GENERATED_AT,
            config_hash=VALID_CONFIG_HASH,
            chunker_version=VALID_CHUNKER_VERSION,
            schemas_version=VALID_SCHEMAS_VERSION,
            counts={"documents": 1},
            source_scopes=["confluence"],  # type: ignore[arg-type]
        )


def test_non_string_source_scope_keys_fail() -> None:
    with pytest.raises(TypeError, match="source_scopes keys must be strings"):
        ManifestRecordBuilder.build(
            dataset_version=VALID_DATASET_VERSION,
            export_mode="full_snapshot",
            generated_at=VALID_GENERATED_AT,
            config_hash=VALID_CONFIG_HASH,
            chunker_version=VALID_CHUNKER_VERSION,
            schemas_version=VALID_SCHEMAS_VERSION,
            counts={"documents": 1},
            source_scopes={1: "scope"},  # type: ignore[dict-item]
        )


def test_mutable_counts_and_source_scopes_are_isolated() -> None:
    counts = {"documents": 1}
    source_scopes = {
        "confluence": {
            "space_keys": ["SVMC"],
            "options": {"include_archived": False},
        }
    }

    record = ManifestRecordBuilder.build(
        dataset_version=VALID_DATASET_VERSION,
        export_mode="full_snapshot",
        generated_at=VALID_GENERATED_AT,
        config_hash=VALID_CONFIG_HASH,
        chunker_version=VALID_CHUNKER_VERSION,
        schemas_version=VALID_SCHEMAS_VERSION,
        counts=counts,
        source_scopes=source_scopes,
    )

    counts["documents"] = 99
    source_scopes["confluence"]["space_keys"].append("OTHER")
    source_scopes["confluence"]["options"]["include_archived"] = True

    assert record["counts"] == {"documents": 1}
    assert record["source_scopes"] == {
        "confluence": {
            "space_keys": ["SVMC"],
            "options": {"include_archived": False},
        }
    }

    record_counts = record["counts"]
    assert isinstance(record_counts, dict)
    record_counts["chunks"] = 2

    record_source_scopes = record["source_scopes"]
    assert isinstance(record_source_scopes, dict)
    record_source_scopes["confluence"]["space_keys"].append(  # type: ignore[index, union-attr]
        "RECORD_ONLY"
    )

    assert counts == {"documents": 99}
    assert source_scopes == {
        "confluence": {
            "space_keys": ["SVMC", "OTHER"],
            "options": {"include_archived": True},
        }
    }


@pytest.mark.parametrize(
    "field_name",
    [
        "dataset_version",
        "export_mode",
        "generated_at",
        "config_hash",
        "chunker_version",
        "schemas_version",
    ],
)
def test_required_string_fields_reject_non_string_values(field_name: str) -> None:
    kwargs = _valid_kwargs()
    kwargs[field_name] = 123

    with pytest.raises(TypeError, match=f"{field_name} expects str"):
        ManifestRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    [
        "dataset_version",
        "export_mode",
        "generated_at",
        "config_hash",
        "chunker_version",
        "schemas_version",
    ],
)
def test_required_string_fields_reject_empty_strings(field_name: str) -> None:
    kwargs = _valid_kwargs()
    kwargs[field_name] = ""

    with pytest.raises(ValueError, match=f"{field_name} must not be empty"):
        ManifestRecordBuilder.build(**kwargs)  # type: ignore[arg-type]


def test_non_string_base_dataset_version_fails() -> None:
    with pytest.raises(TypeError, match="base_dataset_version expects str"):
        ManifestRecordBuilder.build(
            **_valid_kwargs(),
            base_dataset_version=123,  # type: ignore[arg-type]
        )


def test_empty_base_dataset_version_is_preserved_because_schema_allows_string() -> None:
    record = ManifestRecordBuilder.build(
        **_valid_kwargs(),
        base_dataset_version="",
    )

    assert record["base_dataset_version"] == ""
    FoundationSchemaValidator().validate_record("Manifest", record)


def test_caller_owned_metadata_is_preserved_exactly() -> None:
    record = ManifestRecordBuilder.build(
        dataset_version="caller-dataset-version",
        export_mode="caller-export-mode",
        generated_at="caller-generated-at",
        config_hash="caller-config-hash",
        chunker_version="caller-chunker-version",
        schemas_version="caller-schemas-version",
        base_dataset_version="caller-base-version",
        counts={"caller-count": 0},
    )

    assert record["dataset_version"] == "caller-dataset-version"
    assert record["export_mode"] == "caller-export-mode"
    assert record["generated_at"] == "caller-generated-at"
    assert record["config_hash"] == "caller-config-hash"
    assert record["chunker_version"] == "caller-chunker-version"
    assert record["schemas_version"] == "caller-schemas-version"
    assert record["base_dataset_version"] == "caller-base-version"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("export_mode", "not-a-mode"),
        ("config_hash", "not-a-sha256"),
        ("chunker_version", "1"),
    ],
)
def test_schema_validator_owns_schema_facing_validation(
    field_name: str,
    value: str,
) -> None:
    kwargs = _valid_kwargs()
    kwargs[field_name] = value
    record = ManifestRecordBuilder.build(**kwargs)

    with pytest.raises(FoundationValidationError):
        FoundationSchemaValidator().validate_record("Manifest", record)


def test_schema_validation_proves_no_unknown_top_level_fields_are_added() -> None:
    FoundationSchemaValidator().validate_record(
        "Manifest",
        build_minimal_full_snapshot_manifest(),
    )


def test_builder_uses_caller_supplied_dataset_version_and_generated_at() -> None:
    record = ManifestRecordBuilder.build(
        **_valid_kwargs(
            dataset_version="manual-version",
            generated_at="manual-generated-at",
        )
    )

    assert record["dataset_version"] == "manual-version"
    assert record["generated_at"] == "manual-generated-at"


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "dataset_version": VALID_DATASET_VERSION,
        "export_mode": "full_snapshot",
        "generated_at": VALID_GENERATED_AT,
        "config_hash": VALID_CONFIG_HASH,
        "chunker_version": VALID_CHUNKER_VERSION,
        "schemas_version": VALID_SCHEMAS_VERSION,
        "counts": {"documents": 1},
    }
    kwargs.update(overrides)
    return kwargs
