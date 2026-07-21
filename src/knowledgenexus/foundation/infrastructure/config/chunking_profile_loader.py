from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from knowledgenexus.foundation.domain.models.chunking_profile import (
    ChunkingProfile,
    TokenizerAsset,
)


class ChunkingProfileLoadError(ValueError):
    """A sanitized error for an unreadable or malformed chunking profile."""


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChunkingProfileLoadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ChunkingProfileLoadError(f"{field_name} keys must be strings")
    return value


def _exact_keys(
    value: Mapping[str, Any], field_name: str, expected: set[str]
) -> None:
    actual = set(value)
    if actual != expected:
        raise ChunkingProfileLoadError(
            f"{field_name} must contain exactly the active contract fields"
        )


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ChunkingProfileLoadError(f"{field_name} must be a string")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChunkingProfileLoadError(f"{field_name} must be an integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ChunkingProfileLoadError(f"{field_name} must be a boolean")
    return value


def load_chunking_profile(profile_path: Path) -> ChunkingProfile:
    """Load the active profile without resolving or loading tokenizer assets."""

    if not isinstance(profile_path, Path):
        raise TypeError("profile_path expects pathlib.Path")
    try:
        raw_text = profile_path.read_text(encoding="utf-8")
    except OSError:
        raise ChunkingProfileLoadError("chunking profile could not be read") from None
    try:
        loaded = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        raise ChunkingProfileLoadError("chunking profile is invalid YAML") from None

    root = _mapping(loaded, "profile")
    _exact_keys(
        root,
        "profile",
        {
            "schema_version",
            "chunker_version",
            "profile_status",
            "active_profile",
            "embedding_model",
            "active_chunking_profile",
            "benchmark_method",
            "benchmark_profiles",
            "tokenizer_distribution",
        },
    )
    if _integer(root["schema_version"], "schema_version") != 1:
        raise ChunkingProfileLoadError("schema_version is unsupported")

    model = _mapping(root["embedding_model"], "embedding_model")
    _exact_keys(
        model,
        "embedding_model",
        {
            "name",
            "tokenizer",
            "tokenizer_family",
            "vector_dimension",
            "maximum_model_tokens",
            "retrieval_modes",
        },
    )
    retrieval_modes = model["retrieval_modes"]
    if retrieval_modes != ["dense", "sparse", "colbert"]:
        raise ChunkingProfileLoadError(
            "embedding_model.retrieval_modes does not match the active contract"
        )
    active = _mapping(root["active_chunking_profile"], "active_chunking_profile")
    _exact_keys(
        active,
        "active_chunking_profile",
        {
            "target_tokens",
            "minimum_tokens",
            "hard_maximum_tokens",
            "overlap_tokens",
            "code_window_target_tokens",
            "code_window_max_lines",
            "code_window_overlap_lines",
        },
    )
    benchmark_method = _mapping(root["benchmark_method"], "benchmark_method")
    _exact_keys(
        benchmark_method,
        "benchmark_method",
        {"round_1", "round_2", "principle"},
    )
    expected_benchmark_method = {
        "round_1": "dense_only_chunk_budget_sweep",
        "round_2": "fixed_budget_hybrid_retrieval_test",
        "principle": "change_one_variable_at_a_time",
    }
    if dict(benchmark_method) != expected_benchmark_method:
        raise ChunkingProfileLoadError(
            "benchmark_method does not match the recorded benchmark contract"
        )

    benchmark_profiles = _mapping(root["benchmark_profiles"], "benchmark_profiles")
    _exact_keys(
        benchmark_profiles,
        "benchmark_profiles",
        {"control", "small", "medium", "large"},
    )
    budget_keys = (
        "target_tokens",
        "minimum_tokens",
        "hard_maximum_tokens",
        "overlap_tokens",
    )
    parsed_benchmark_profiles: dict[str, dict[str, int]] = {}
    for name in ("control", "small", "medium", "large"):
        candidate = _mapping(
            benchmark_profiles[name], f"benchmark_profiles.{name}"
        )
        _exact_keys(candidate, f"benchmark_profiles.{name}", set(budget_keys))
        parsed = {
            key: _integer(candidate[key], f"benchmark_profiles.{name}.{key}")
            for key in budget_keys
        }
        if not (
            0 < parsed["minimum_tokens"]
            <= parsed["target_tokens"]
            <= parsed["hard_maximum_tokens"]
            < _integer(
                model["maximum_model_tokens"], "embedding_model.maximum_model_tokens"
            )
        ):
            raise ChunkingProfileLoadError(
                f"benchmark_profiles.{name} has invalid token limits"
            )
        if not 0 < parsed["overlap_tokens"] < parsed["target_tokens"]:
            raise ChunkingProfileLoadError(
                f"benchmark_profiles.{name} has invalid overlap"
            )
        parsed_benchmark_profiles[name] = parsed
    if any(
        parsed_benchmark_profiles["medium"][key] != _integer(active[key], key)
        for key in budget_keys
    ):
        raise ChunkingProfileLoadError(
            "active_chunking_profile must match the medium benchmark candidate"
        )
    distribution = _mapping(
        root["tokenizer_distribution"], "tokenizer_distribution"
    )
    _exact_keys(
        distribution,
        "tokenizer_distribution",
        {
            "source_repository",
            "upstream_commit",
            "observed_license",
            "provenance_url",
            "external_bundle_required",
            "implicit_cache_allowed",
            "required_assets",
            "pinned_versions",
        },
    )
    if not _boolean(
        distribution["external_bundle_required"],
        "tokenizer_distribution.external_bundle_required",
    ):
        raise ChunkingProfileLoadError("external tokenizer bundle must be required")
    if _boolean(
        distribution["implicit_cache_allowed"],
        "tokenizer_distribution.implicit_cache_allowed",
    ):
        raise ChunkingProfileLoadError("implicit tokenizer cache must be disabled")

    raw_assets = distribution["required_assets"]
    if isinstance(raw_assets, (str, bytes)) or not isinstance(raw_assets, list):
        raise ChunkingProfileLoadError(
            "tokenizer_distribution.required_assets must be a list"
        )
    assets: list[TokenizerAsset] = []
    for index, raw_asset in enumerate(raw_assets):
        field_name = f"tokenizer_distribution.required_assets[{index}]"
        asset = _mapping(raw_asset, field_name)
        _exact_keys(asset, field_name, {"filename", "byte_size", "sha256"})
        try:
            assets.append(
                TokenizerAsset(
                    filename=_string(asset["filename"], f"{field_name}.filename"),
                    byte_size=_integer(asset["byte_size"], f"{field_name}.byte_size"),
                    sha256=_string(asset["sha256"], f"{field_name}.sha256"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ChunkingProfileLoadError(str(exc)) from None

    versions = _mapping(
        distribution["pinned_versions"], "tokenizer_distribution.pinned_versions"
    )
    _exact_keys(
        versions,
        "tokenizer_distribution.pinned_versions",
        {"transformers", "tokenizers", "sentencepiece"},
    )

    try:
        return ChunkingProfile(
            chunker_version=_string(root["chunker_version"], "chunker_version"),
            profile_status=_string(root["profile_status"], "profile_status"),
            active_profile=_string(root["active_profile"], "active_profile"),
            model_name=_string(model["name"], "embedding_model.name"),
            tokenizer_name=_string(model["tokenizer"], "embedding_model.tokenizer"),
            tokenizer_family=_string(
                model["tokenizer_family"], "embedding_model.tokenizer_family"
            ),
            vector_dimension=_integer(
                model["vector_dimension"], "embedding_model.vector_dimension"
            ),
            maximum_model_tokens=_integer(
                model["maximum_model_tokens"],
                "embedding_model.maximum_model_tokens",
            ),
            target_tokens=_integer(
                active["target_tokens"], "active_chunking_profile.target_tokens"
            ),
            minimum_tokens=_integer(
                active["minimum_tokens"], "active_chunking_profile.minimum_tokens"
            ),
            hard_maximum_tokens=_integer(
                active["hard_maximum_tokens"],
                "active_chunking_profile.hard_maximum_tokens",
            ),
            overlap_tokens=_integer(
                active["overlap_tokens"], "active_chunking_profile.overlap_tokens"
            ),
            code_window_target_tokens=_integer(
                active["code_window_target_tokens"],
                "active_chunking_profile.code_window_target_tokens",
            ),
            code_window_max_lines=_integer(
                active["code_window_max_lines"],
                "active_chunking_profile.code_window_max_lines",
            ),
            code_window_overlap_lines=_integer(
                active["code_window_overlap_lines"],
                "active_chunking_profile.code_window_overlap_lines",
            ),
            tokenizer_repository=_string(
                distribution["source_repository"],
                "tokenizer_distribution.source_repository",
            ),
            tokenizer_revision=_string(
                distribution["upstream_commit"],
                "tokenizer_distribution.upstream_commit",
            ),
            observed_license=_string(
                distribution["observed_license"],
                "tokenizer_distribution.observed_license",
            ),
            provenance_url=_string(
                distribution["provenance_url"],
                "tokenizer_distribution.provenance_url",
            ),
            tokenizer_assets=tuple(assets),
            transformers_version=_string(
                versions["transformers"],
                "tokenizer_distribution.pinned_versions.transformers",
            ),
            tokenizers_version=_string(
                versions["tokenizers"],
                "tokenizer_distribution.pinned_versions.tokenizers",
            ),
            sentencepiece_version=_string(
                versions["sentencepiece"],
                "tokenizer_distribution.pinned_versions.sentencepiece",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ChunkingProfileLoadError(str(exc)) from None
