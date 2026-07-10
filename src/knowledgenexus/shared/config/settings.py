from enum import StrEnum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageMode(StrEnum):
    HYBRID = "hybrid"
    POSTGRES = "postgres"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    storage_mode: StorageMode = StorageMode.HYBRID
    database_url: str = "sqlite:///./data/index/knowledgenexus.db"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledgenexus"
    qdrant_api_key: str | None = None

    # Embedding
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_cache_dir: str = "./data/index/models"
    embedding_batch_size: int = 32

    @property
    def project_root(self) -> Path:
        # src/knowledgenexus/shared/config/settings.py -> repo root
        return Path(__file__).resolve().parents[4]

    @property
    def qdrant_collection_config_path(self) -> Path:
        return self.project_root / "config" / "qdrant.collection.yaml"


def get_settings() -> Settings:
    return Settings()
