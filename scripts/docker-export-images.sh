#!/usr/bin/env bash
# Run this on a machine WITH Docker + internet access, after building the
# stack once (`docker compose build`). It bundles all 3 images used by
# docker-compose.yml into portable .tar files under docker/vendor/, so a
# machine WITHOUT internet access can later `docker load` them and run
# `docker compose up -d` with zero network calls (no Docker Hub pull, no
# rebuild).
set -euo pipefail

cd "$(dirname "$0")/.."

OUT_DIR="docker/vendor"
mkdir -p "$OUT_DIR"

QDRANT_IMAGE="qdrant/qdrant:v1.12.6"
API_IMAGE="knowledgenexus-api:latest"
MCP_IMAGE="knowledgenexus-mcp:latest"

echo "==> Pulling $QDRANT_IMAGE from Docker Hub..."
docker pull "$QDRANT_IMAGE"

echo "==> Building api/mcp images (docker compose build)..."
docker compose build api mcp

echo "==> Saving images to $OUT_DIR/*.tar ..."
docker save -o "$OUT_DIR/qdrant.tar" "$QDRANT_IMAGE"
docker save -o "$OUT_DIR/knowledgenexus-api.tar" "$API_IMAGE"
docker save -o "$OUT_DIR/knowledgenexus-mcp.tar" "$MCP_IMAGE"

echo "==> Done. Copy the whole '$OUT_DIR' folder (plus this repo) to the"
echo "    offline machine, then run scripts/docker-import-images.sh there."
du -sh "$OUT_DIR"/*.tar
