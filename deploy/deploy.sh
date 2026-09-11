#!/usr/bin/env bash
# Deploy (or redeploy) the grader on the droplet.
#
#   ./deploy.sh              # runs the tag from .env (GRADER_IMAGE_TAG) or "main"
#   ./deploy.sh sha-1a2b3c4  # pin a specific build
#   ./deploy.sh v0.2.0       # or a release tag -> image tag 0.2.0
#
# Run as the "deploy" user from /srv/grader, which holds docker-compose.prod.yml
# and .env. Steps: pull images, run migrations (aborts on failure, leaving the
# running services untouched), start web/worker/proxy, prune old images.

set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
compose() { docker compose -f "${COMPOSE_FILE}" "$@"; }

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "missing ${COMPOSE_FILE} in $(pwd)" >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "missing .env in $(pwd) (see deploy/README.md)" >&2
  exit 1
fi

# Optional image tag argument. Release tags v1.2.3 are pushed as 1.2.3.
if [[ $# -ge 1 && -n "$1" ]]; then
  GRADER_IMAGE_TAG="${1#v}"
  export GRADER_IMAGE_TAG
fi
echo "==> Deploying image tag: ${GRADER_IMAGE_TAG:-$(grep -E '^GRADER_IMAGE_TAG=' .env | cut -d= -f2- || true)}"
echo "    (empty means the compose default, main)"

echo "==> Pulling images"
compose pull --quiet

# Named volumes are created root-owned; the backend image runs as uid 10001.
# Chown once so the worker can write its caches (no-op when already correct).
echo "==> Preparing volumes"
for vol in artifacts hf_cache uv_cache sandboxes; do
  docker volume create "grader_${vol}" >/dev/null
  docker run --rm -v "grader_${vol}:/v" alpine:3 sh -c \
    '[ "$(stat -c %u /v)" = 10001 ] || chown 10001:10001 /v'
done

echo "==> Running migrations"
compose run --rm migrate

echo "==> Starting services"
compose up -d --remove-orphans web worker proxy

echo "==> Waiting for web to become healthy"
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$(compose ps -q web)" 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  sleep 2
done
if [[ "${status:-}" != "healthy" ]]; then
  echo "web is not healthy (${status:-unknown}); recent logs:" >&2
  compose logs --tail=50 web >&2
  exit 1
fi

echo "==> Pruning old images"
docker image prune -f >/dev/null

echo "==> Status"
compose ps
