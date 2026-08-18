"""HTTP helpers for the agent CLI (stdlib only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _load_env_file() -> None:
    """Load .env file from repo root if it exists (stdlib only, no python-dotenv)."""
    # Walk up from this file to find the repo root (where pyproject.toml lives)
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pyproject.toml").exists():
            break
        current = current.parent
    else:
        return

    env_file = current / ".env"
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        # Only set if not already in environment (env vars take precedence)
        if key and key not in os.environ:
            os.environ[key] = value


# Load .env before reading API_BASE_URL
_load_env_file()

API_BASE_URL = os.environ.get("KNOWLEDGENEXUS_API_URL", "http://localhost:8000")
TIMEOUT = 120  # seconds (BGE-M3 may need time to load on first search)


class CliError(Exception):
    """Raised when a CLI API call fails. Callers should catch and exit(1)."""


def make_request(
    method: str,
    endpoint: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call KnowledgeNexus API; raise CliError on failure (does NOT call sys.exit)."""
    url = f"{API_BASE_URL}{endpoint}"

    if params:
        query_parts = [
            f"{key}={value}" for key, value in params.items() if value is not None
        ]
        if query_parts:
            url += "?" + "&".join(query_parts)

    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url, data=body, headers=headers, method=method)

    try:
        with urlopen(req, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            error_detail = json.loads(error_body).get("detail", error_body)
        except (json.JSONDecodeError, ValueError):
            error_detail = error_body
        raise CliError(f"API Error ({e.code}): {error_detail}") from e
    except URLError as e:
        raise CliError(
            f"Connection Error: {e.reason}\n"
            f"   Is KnowledgeNexus API running at {API_BASE_URL}?"
        ) from e
    except Exception as e:
        raise CliError(f"Unexpected error: {e}") from e
