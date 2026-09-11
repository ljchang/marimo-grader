# Caddy image that carries the built Svelte frontend and terminates TLS.
# Build context: repository root.
#
#   docker build -t ghcr.io/ljchang/marimo-grader-web -f deploy/web/Dockerfile .
#
# Stage 1 mirrors frontend/Dockerfile so the two never drift.
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.1.2 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
RUN pnpm check && pnpm build

# Stage 2: Caddy serves /srv and proxies /api to the backend container.
# Automatic HTTPS (Let's Encrypt) keys off GRADER_HOST at runtime; the
# certificate store lives in /data (mount the caddy_data volume there).
FROM caddy:2-alpine
COPY deploy/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
