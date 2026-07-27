# OpenAPI Retrieve Endpoint

Contract surface for search:

```http
POST /api/v1/retrieve
```

Body fields: `query`, `top_k`, `score_threshold`, `filters`.

The agent CLI `uv run kn search` is a thin HTTP client over this endpoint. Do not confuse
it with foundation ingest CLIs.
