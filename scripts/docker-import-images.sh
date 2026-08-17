#!/usr/bin/env bash
# Run this on the OFFLINE/air-gapped machine, after copying docker/vendor/*.tar
# here from a machine that ran scripts/docker-export-images.sh. Loads all 3
# images into the local Docker image cache so `docker compose up -d` runs
# with no network access at all (no Docker Hub pull, no build).
set -euo pipefail

cd "$(dirname "$0")/.."

IN_DIR="docker/vendor"

for tar in "$IN_DIR"/qdrant.tar "$IN_DIR"/knowledgenexus-api.tar "$IN_DIR"/knowledgenexus-mcp.tar; do
    if [ ! -f "$tar" ]; then
        echo "Missing $tar — did you copy docker/vendor/ from the export machine?" >&2
        exit 1
    fi
    echo "==> Loading $tar ..."
    docker load -i "$tar"
done

echo "==> Done. Images are now in the local Docker cache — you can run:"
echo "    docker compose up -d"
echo "    (it will NOT pull or rebuild, since the tags already match)"
