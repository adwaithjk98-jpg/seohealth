#!/usr/bin/env bash
# SEO Health — production deploy. Pulls the pre-built images from GHCR and brings
# the stack up. It NEVER builds on the box (images come from CI — see
# .github/workflows/build-images.yml and docker-compose.registry.yml).
#
# Run from the repo root ON THE VPS, after .env.prod exists and you've done the
# one-time `docker login ghcr.io` (see deploy/README.md).
#
# Usage:
#   ./deploy.sh                       # deploy the latest pushed images
#   IMAGE_TAG=sha-abc1234 ./deploy.sh # deploy/rollback to a specific build
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env.prod ]; then
  echo "ERROR: .env.prod not found. Copy .env.prod.example -> .env.prod, fill it in, then: chmod 600 .env.prod" >&2
  exit 1
fi

COMPOSE=(docker compose --env-file .env.prod
  -f docker-compose.yml
  -f docker-compose.prod.yml
  -f docker-compose.registry.yml
  -f docker-compose.caddy.yml)

echo "==> Pulling images (IMAGE_TAG=${IMAGE_TAG:-latest})"
"${COMPOSE[@]}" pull

echo "==> Starting stack"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> Pruning dangling images"
docker image prune -f >/dev/null || true

echo "==> Services:"
"${COMPOSE[@]}" ps

# The API container runs `alembic upgrade head` on start, so a fresh deploy may
# take a few seconds before /api/health is green; Caddy also needs ~30s to
# obtain the TLS cert on the very first boot.
DOMAIN="$(grep -E '^FRONTEND_BASE_URL=' .env.prod | cut -d= -f2- | tr -d '\r')"
echo
echo "==> Verify once it settles:"
echo "    curl -s ${DOMAIN%/}/api/health   # expect status:ok + scheduler heartbeat"
