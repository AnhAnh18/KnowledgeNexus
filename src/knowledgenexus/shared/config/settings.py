from enum import StrEnum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageMode(StrEnum):
    HYBRID = "hybrid"
    POSTGRES = "postgres"


class RetrievalMode(StrEnum):
    DENSE = "dense"
    HYBRID = "hybrid"


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
    qdrant_collection: str = "Confluence"
    qdrant_api_key: str | None = None

    # Retrieval mode: "dense" (default) or "hybrid" (dense + sparse + RRF)
    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID

    # CORS (comma-separated origins, or "*" for all)
    cors_origins: str = "*"

    # Embedding
    embedding_model: str = "BAAI/bge-m3"
    embedding_model_path: str | None = None
    embedding_dimension: int = 1024
    embedding_device: str = "cpu"
    embedding_cache_dir: str = "./data/index/models"
    embedding_batch_size: int = 32

    # Confluence (live single-page ingestion)
    confluence_base_url: str | None = None
    confluence_pat: str | None = None
    confluence_raw_root: str = "./data/confluence-raw"
    confluence_chunking_profile_path: str = "./contracts/foundation/embedding_profile.yaml"
    # External durable workspaces for URL-rooted Foundation packets.  This is
    # server policy, never an API parameter supplied by a browser.  No usable
    # default: the workspace guard rejects any path inside the repository, so
    # the old "./data/confluence-snapshots" could never work and merely made
    # the setting look configured.  Empty means the operator must set it.
    confluence_snapshot_root: str = ""
    confluence_max_pages: int = 200

    # Reranker (cross-encoder, post-retrieval stage)
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_model_path: str | None = None
    reranker_device: str = "cpu"
    reranker_batch_size: int = 16
    # Number of candidates to retrieve before reranking (over-fetch factor)
    rerank_candidate_count: int = 50

    @property
    def project_root(self) -> Path:
        # src/knowledgenexus/shared/config/settings.py -> repo root
        return Path(__file__).resolve().parents[4]

    @property
    def qdrant_collection_config_path(self) -> Path:
        if self.retrieval_mode == RetrievalMode.HYBRID:
            return self.project_root / "config" / "qdrant.collection.hybrid.yaml"
        return self.project_root / "config" / "qdrant.collection.yaml"


def get_settings() -> Settings:
    return Settings()
