from pathlib import Path

from knowledgenexus.shared.config.settings import Settings


def resolve_embedding_model_path(settings: Settings) -> str:
    """
    Resolve model location for FlagEmbedding.

    Priority:
    1. EMBEDDING_MODEL_PATH — local folder (symlink or copied weights)
    2. EMBEDDING_MODEL — HuggingFace repo id (downloads to EMBEDDING_CACHE_DIR)
    """
    if settings.embedding_model_path:
        raw = Path(settings.embedding_model_path)
        path = raw if raw.is_absolute() else settings.project_root / raw
        if path.exists():
            return str(path.resolve())
        raise FileNotFoundError(
            f"EMBEDDING_MODEL_PATH does not exist: {path}. "
            "Point to a local BGE-M3 folder or symlink."
        )
    return settings.embedding_model


def resolve_embedding_cache_dir(settings: Settings) -> Path:
    raw = Path(settings.embedding_cache_dir)
    cache = raw if raw.is_absolute() else settings.project_root / raw
    cache.mkdir(parents=True, exist_ok=True)
    return cache
