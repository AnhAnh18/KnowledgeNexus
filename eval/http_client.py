"""HTTP client for eval (raises instead of sys.exit)."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EvalHttpError(RuntimeError):
    """API or connection failure during eval."""


def request_json(
    method: str,
    base_url: str,
    endpoint: str,
    *,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{endpoint}"
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
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(error_body).get("detail", error_body)
        except (json.JSONDecodeError, ValueError):
            detail = error_body
        raise EvalHttpError(f"API Error ({e.code}): {detail}") from e
    except URLError as e:
        raise EvalHttpError(
            f"Connection Error: {e.reason}. Is API running at {base_url}?"
        ) from e
