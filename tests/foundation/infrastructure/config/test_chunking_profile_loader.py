from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from knowledgenexus.foundation.infrastructure.config import (
    ChunkingProfileLoadError,
    load_chunking_profile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROFILE_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"


def _profile_mapping() -> dict[str, object]:
    loaded = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write_profile(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_loads_active_repository_profile() -> None:
    profile = load_chunking_profile(PROFILE_PATH)

    assert profile.chunker_version == "1.2.0"
    assert profile.profile_status == "provisional_until_benchmark"
    assert profile.active_profile == "medium"
    assert profile.model_name == "BAAI/bge-m3"
    assert profile.target_tokens == 450
    assert profile.minimum_tokens == 96
    assert profile.hard_maximum_tokens == 1000
    assert profile.overlap_tokens == 64
    assert profile.code_window_target_tokens == 450
    assert profile.code_window_max_lines == 40
    assert profile.code_window_overlap_lines == 4
    assert profile.tokenizer_repository == "https://huggingface.co/BAAI/bge-m3"
    assert profile.tokenizer_revision == "5617a9f61b028005a4858fdac845db406aefb181"
    assert profile.observed_license == "MIT"
    assert profile.transformers_version == "4.57.6"
    assert profile.tokenizers_version == "0.22.2"
    assert profile.sentencepiece_version == "0.2.2"
    asset = profile.tokenizer_assets[0]
    assert asset.filename == "tokenizer.json"
    assert asset.byte_size == 17_098_108
    assert asset.sha256 == (
        "21106b6d7dab2952c1d496fb21d5dc9d"
        "b75c28ed361a05f5020bbba27810dd08"
    )


def test_rejects_unknown_or_missing_fields(tmp_path: Path) -> None:
    unknown = _profile_mapping()
    unknown["unexpected"] = True
    missing = _profile_mapping()
    del missing["active_profile"]

    for data in (unknown, missing):
        with pytest.raises(ChunkingProfileLoadError, match="exactly"):
            load_chunking_profile(_write_profile(tmp_path, data))


def test_rejects_implicit_cache_or_non_external_bundle(tmp_path: Path) -> None:
    for field_name, value in (
        ("implicit_cache_allowed", True),
        ("external_bundle_required", False),
    ):
        data = _profile_mapping()
        distribution = data["tokenizer_distribution"]
        assert isinstance(distribution, dict)
        distribution[field_name] = value
        with pytest.raises(ChunkingProfileLoadError):
            load_chunking_profile(_write_profile(tmp_path, data))


def test_rejects_invalid_profile_relationship(tmp_path: Path) -> None:
    data = _profile_mapping()
    active = data["active_chunking_profile"]
    assert isinstance(active, dict)
    active["code_window_target_tokens"] = 1001

    with pytest.raises(ChunkingProfileLoadError, match="must not exceed"):
        load_chunking_profile(_write_profile(tmp_path, data))


def test_rejects_active_medium_candidate_drift(tmp_path: Path) -> None:
    data = _profile_mapping()
    candidates = data["benchmark_profiles"]
    assert isinstance(candidates, dict)
    medium = candidates["medium"]
    assert isinstance(medium, dict)
    medium["target_tokens"] = 451

    with pytest.raises(ChunkingProfileLoadError, match="medium benchmark"):
        load_chunking_profile(_write_profile(tmp_path, data))


def test_errors_do_not_disclose_raw_yaml_or_path(tmp_path: Path) -> None:
    marker = "sensitive-fixture-marker"
    path = tmp_path / marker / "profile.yaml"
    path.parent.mkdir()
    path.write_text(f"{marker}: [", encoding="utf-8")

    with pytest.raises(ChunkingProfileLoadError) as captured:
        load_chunking_profile(path)

    assert marker not in str(captured.value)


def test_requires_pathlib_path() -> None:
    with pytest.raises(TypeError, match="pathlib.Path"):
        load_chunking_profile("profile.yaml")  # type: ignore[arg-type]
