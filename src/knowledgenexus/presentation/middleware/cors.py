from __future__ import annotations

from dataclasses import dataclass

from fastapi.middleware.cors import CORSMiddleware

from knowledgenexus.shared.config.settings import get_settings


@dataclass
class CORSConfig:
    """Holds parsed CORS configuration from settings."""

    allow_origins: list[str]
    allow_credentials: bool
    allow_methods: list[str]
    allow_headers: list[str]
    expose_headers: list[str]
    max_age: int


def get_cors_config() -> CORSConfig:
    """Read settings and build a CORSConfig instance.

    Returns:
        CORSConfig with parsed origins, credentials flag, etc.
    """
    settings = get_settings()
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

    if "*" in origins:
        allow_origins = ["*"]
        allow_credentials = False  # CORS spec: wildcard incompatible with credentials
    else:
        allow_origins = origins
        allow_credentials = True

    return CORSConfig(
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=600,
    )


def get_cors_middleware_kwargs() -> dict:
    """Return kwargs dict for app.add_middleware(CORSMiddleware, **kwargs).

    Usage:
        from fastapi.middleware.cors import CORSMiddleware
        from knowledgenexus.presentation.middleware.cors import get_cors_middleware_kwargs

        app.add_middleware(CORSMiddleware, **get_cors_middleware_kwargs())
    """
    config = get_cors_config()
    return {
        "allow_origins": config.allow_origins,
        "allow_credentials": config.allow_credentials,
        "allow_methods": config.allow_methods,
        "allow_headers": config.allow_headers,
        "expose_headers": config.expose_headers,
        "max_age": config.max_age,
    }
