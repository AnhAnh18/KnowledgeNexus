# Build context is the repo root (see docker-compose.yml: context: ., dockerfile: docker/api/Dockerfile)
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install CPU-only torch first so the "embedding" extra doesn't pull CUDA wheels.
RUN uv pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && uv pip install -e ".[embedding]"

# Model weights must be staged locally before build — see docker/models/README.md.
# Baked into the image so the container needs no network access at runtime.
COPY docker/models/bge-m3 /app/models/bge-m3
COPY docker/models/bge-reranker-v2-m3 /app/models/bge-reranker-v2-m3


FROM python:3.11-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY src ./src
COPY config ./config
COPY contracts ./contracts
COPY demo ./demo
COPY pyproject.toml ./
COPY --from=builder /app/models /app/models

ENV PYTHONPATH=/app/src \
    EMBEDDING_MODEL_PATH=/app/models/bge-m3 \
    RERANKER_MODEL_PATH=/app/models/bge-reranker-v2-m3 \
    EMBEDDING_DEVICE=cpu \
    RERANKER_DEVICE=cpu

RUN mkdir -p /app/data/index /app/data/confluence-raw /app/data/confluence-snapshots \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "knowledgenexus.presentation.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
