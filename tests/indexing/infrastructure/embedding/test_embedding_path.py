from pathlib import Path

import pytest

from knowledgenexus.shared.config.settings import Settings
from knowledgenexus.indexing.infrastructure.embedding.model_path import (
    resolve_embedding_cache_dir,
    resolve_embedding_model_path,
)


def test_resolve_embedding_model_path_uses_hf_id_when_no_local_path():
    settings = Settings(embedding_model="BAAI/bge-m3", embedding_model_path=None)

    assert resolve_embedding_model_path(settings) == "BAAI/bge-m3"


def test_resolve_embedding_model_path_uses_local_folder(project_root: Path, tmp_path: Path):
    model_dir = tmp_path / "bge-m3"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    settings = Settings(
        embedding_model="BAAI/bge-m3",
        embedding_model_path=str(model_dir),
    )

    assert resolve_embedding_model_path(settings) == str(model_dir.resolve())


def test_resolve_embedding_model_path_relative_to_project_root(project_root: Path):
    model_dir = project_root / "relative-model-test"
    model_dir.mkdir(exist_ok=True)
    try:
        settings = Settings(embedding_model_path="relative-model-test")
        assert resolve_embedding_model_path(settings) == str(model_dir.resolve())
    finally:
        model_dir.rmdir()


def test_resolve_embedding_model_path_missing_raises(tmp_path: Path):
    settings = Settings(embedding_model_path=str(tmp_path / "missing-model"))

    with pytest.raises(FileNotFoundError, match="EMBEDDING_MODEL_PATH does not exist"):
        resolve_embedding_model_path(settings)


def test_resolve_embedding_cache_dir_creates_folder(project_root: Path, tmp_path: Path):
    cache = tmp_path / "hf-cache"
    settings = Settings(embedding_cache_dir=str(cache))

    resolved = resolve_embedding_cache_dir(settings)

    assert resolved == cache.resolve()
    assert cache.is_dir()
