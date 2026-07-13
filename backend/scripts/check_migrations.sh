#!/usr/bin/env bash
# Migration drift check (MONEY_TESTS_SPEC.md §"Migration drift check").
#
# Kills the dev/prod migration-drift class (dev is SQLite, prod is Postgres —
# the push-500 stale-migration bug came from exactly this gap). Spins up a
# throwaway Postgres, runs every Alembic migration against it, then asserts the
# models and the migration head agree (no un-migrated schema changes).
#
# Run before every deploy; wire into CI when CI exists.
#
# Requires: docker, and the Postgres driver (psycopg2) importable by the venv.
# Usage: backend/scripts/check_migrations.sh   (run from anywhere)
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BACKEND_DIR"

CONTAINER="seohealth_migcheck_pg"
PORT=54329
export DATABASE_URL="postgresql://postgres:migcheck@localhost:${PORT}/postgres"
PY="${PY:-.venv/bin/python}"

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> starting throwaway Postgres (postgres:16) on :${PORT}"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --rm --name "$CONTAINER" \
  -e POSTGRES_PASSWORD=migcheck -p "${PORT}:5432" postgres:16 >/dev/null

echo -n "==> waiting for Postgres to accept connections"
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
    echo " — ready"; break
  fi
  echo -n "."; sleep 1
done

echo "==> alembic upgrade head"
"$PY" -m alembic upgrade head

echo "==> alembic check (models vs migration head must agree)"
if "$PY" -m alembic check; then
  echo "✅ migrations are in sync with the models — no drift"
else
  echo "❌ DRIFT: models have changes not captured in a migration."
  echo "   Run:  DATABASE_URL=... .venv/bin/python -m alembic revision --autogenerate -m '<desc>'"
  exit 1
fi
