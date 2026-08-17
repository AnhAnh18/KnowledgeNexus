# Offline image bundle

This folder holds exported `.tar` copies of the 3 images the stack needs
(`qdrant/qdrant`, `knowledgenexus-api`, `knowledgenexus-mcp`), so the stack
can be deployed to a machine with **no internet access at all** — no Docker
Hub pull, no `pip`/`npm` install.

## On a machine WITH Docker + internet

```bash
# bash
scripts/docker-export-images.sh
# or on Windows
scripts\docker-export-images.bat
```

This pulls `qdrant/qdrant`, builds `api`/`mcp` via `docker compose build`,
then saves all 3 to `docker/vendor/*.tar` (a few GB total — mostly the `api`
image with the baked-in embedding/reranker models).

## On the offline/air-gapped machine

Copy this repo (including `docker/vendor/*.tar`, `docker/models/`, `.env`,
`.env.docker`) to the target machine, then:

```bash
# bash
scripts/docker-import-images.sh
# or on Windows
scripts\docker-import-images.bat

docker compose up -d
```

`docker load` registers the images under the exact tags `docker-compose.yml`
expects (`qdrant/qdrant:v1.12.6`, `knowledgenexus-api:latest`,
`knowledgenexus-mcp:latest`), so `docker compose up -d` finds them already
present locally and starts the containers directly — it does not pull or
rebuild anything.

## Note

The `.tar` files here are gitignored (multi-GB) — this folder is a drop
point for a manual copy/transfer step, not something committed to git.
