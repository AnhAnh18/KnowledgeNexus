from pathlib import Path

from knowledgenexus.shared.config.settings import Settings


def resolve_embedding_model_path(settings: Settings) -> str:
    """
    Resolve model location for FlagEmbedding.

    Requires EMBEDDING_MODEL_PATH to be set.
    Raises FileNotFoundError if model not found (no auto-download).
    """
    if not settings.embedding_model_path:
        raise FileNotFoundError(
            "EMBEDDING_MODEL_PATH is required. "
            "Please set the path to your local BGE-M3 model folder. "
            "Auto-download from HuggingFace is not supported."
        )

    raw = Path(settings.embedding_model_path)
    path = raw if raw.is_absolute() else settings.project_root / raw

    if not path.exists():
        raise FileNotFoundError(
            f"Embedding model not found at: {path}. "
            "Please ensure the model folder exists and contains the BGE-M3 weights."
        )

    return str(path.resolve())
