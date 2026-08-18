#!/usr/bin/env bash
# Gathers the minimal set of files an offline/air-gapped target machine
# needs to run the Docker stack.
#
# NOTE: Models are NOT included in this package. They are stored externally
# at D:/KnowledgeNexus_Models/ and mounted via docker-compose.yml volume.
#
# Run scripts/docker-export-images.sh FIRST so docker/vendor/*.tar exist.
set -euo pipefail

cd "$(dirname "$0")/.."

PKG_DIR="dist/knowledgenexus-deploy"
ZIP_PATH="dist/knowledgenexus-deploy.zip"

for f in docker/vendor/qdrant.tar docker/vendor/knowledgenexus-api.tar docker/vendor/knowledgenexus-mcp.tar; do
    if [ ! -f "$f" ]; then
        echo "Missing $f -- run scripts/docker-export-images.sh first." >&2
        exit 1
    fi
done
if [ ! -f .env ]; then
    echo "Missing .env -- fill it in before packaging." >&2
    exit 1
fi
if [ ! -f .env.docker ]; then
    echo "Missing .env.docker -- copy .env.docker.example to .env.docker and fill it in first." >&2
    exit 1
fi

echo "==> This package will contain real secrets from .env (e.g. CONFLUENCE_PAT)."
echo "    Handle $ZIP_PATH like a credential -- do not upload it anywhere public."
echo

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/docker/vendor" "$PKG_DIR/scripts"

echo "==> Copying deploy files into $PKG_DIR ..."
cp docker-compose.yml "$PKG_DIR/"
cp .env "$PKG_DIR/"
cp .env.docker "$PKG_DIR/"
cp docker/vendor/qdrant.tar docker/vendor/knowledgenexus-api.tar docker/vendor/knowledgenexus-mcp.tar "$PKG_DIR/docker/vendor/"
cp scripts/docker-import-images.sh scripts/docker-import-images.bat "$PKG_DIR/scripts/"
chmod +x "$PKG_DIR/scripts/docker-import-images.sh"

echo "==> Zipping to $ZIP_PATH ..."
rm -f "$ZIP_PATH"
(cd "$PKG_DIR" && zip -r "../../$ZIP_PATH" .) >/dev/null

echo
echo "==> Done: $ZIP_PATH"
echo
echo "    DEPLOYMENT INSTRUCTIONS:"
echo "    ========================"
echo "    1. Copy this zip file to the offline/air-gapped machine"
echo "    2. Copy the models folder (D:/KnowledgeNexus_Models/) separately"
echo "       - This is NOT included in the zip (too large, ~2.3GB)"
echo "       - Share this folder once via network/USB"
echo "    3. On the target machine, extract the zip"
echo "    4. Run: scripts/docker-import-images.sh"
echo "    5. Ensure models exist at D:/KnowledgeNexus_Models/ on target machine"
echo "       (or update .env with the actual models path)"
echo "    6. Run: docker compose up -d"
echo
echo "    NOTE: The docker-compose.yml expects models at D:/KnowledgeNexus_Models/"
echo "          If your target machine uses a different path, update .env BEFORE"
echo "          running docker compose up -d"
