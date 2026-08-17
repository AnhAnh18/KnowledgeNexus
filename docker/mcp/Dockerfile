# Build context is the repo root (see docker-compose.yml: context: ., dockerfile: docker/mcp/Dockerfile)
FROM node:20-slim AS builder

WORKDIR /app

COPY mcp/package.json mcp/package-lock.json ./
RUN npm ci

COPY mcp/tsconfig.json ./
COPY mcp/src ./src
RUN npm run build


FROM node:20-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY mcp/package.json mcp/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/build ./build

ENV MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8787

USER app

EXPOSE 8787

CMD ["node", "build/index.js"]
