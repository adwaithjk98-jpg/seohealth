#!/usr/bin/env bash
# SEO Health — nightly Postgres backup (pg_dump custom format + rotation).
#
# Takes a compressed, pg_restore-able dump of $DATABASE_URL into $BACKUP_DIR as
# seohealth-YYYYMMDD-HHMMSS.dump, then prunes to the newest $KEEP dumps.
#
# Prod (cron, on the VPS) — dump to a path OUTSIDE the app dir / volume:
#   30 2 * * *  DATABASE_URL=... BACKUP_DIR=/var/backups/seohealth \
#     /srv/seohealth/backend/scripts/backup_db.sh >> /var/log/seohealth-backup.log 2>&1
#
# Restore drill (into a THROWAWAY db — never prod; see also the runbook):
#   createdb seohealth_restore_test
#   pg_restore --no-owner --clean --if-exists -d seohealth_restore_test <dump>
#   psql seohealth_restore_test -c '\dt'      # eyeball the tables/rows
#   dropdb seohealth_restore_test
#
# Env:
#   DATABASE_URL  required. Accepts the SQLAlchemy form (postgresql+psycopg://…)
#                 — the +driver suffix is stripped for pg_dump's libpq parser.
#   BACKUP_DIR    default ./backups
#   KEEP          default 14 (nightly → ~two weeks of history)
set -euo pipefail

DB_URL="${DATABASE_URL:?DATABASE_URL must be set (the Postgres connection to back up)}"
# pg_dump speaks plain libpq URLs — drop SQLAlchemy's +psycopg[2] driver suffix.
DB_URL="${DB_URL/postgresql+psycopg2:/postgresql:}"
DB_URL="${DB_URL/postgresql+psycopg:/postgresql:}"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP="${KEEP:-14}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/seohealth-$STAMP.dump"

echo "==> [$(date -u +%FT%TZ)] backing up to $OUT"
# -Fc: custom format — compressed and restorable selectively via pg_restore.
# --no-owner: keep the dump portable across differing role names (prod vs drill).
pg_dump -Fc --no-owner "$DB_URL" -f "$OUT"
echo "==> wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Rotation: keep the newest $KEEP dumps by mtime, prune the rest. Piped
# while-read (no mapfile) so it runs on macOS's bash 3.2 too.
ls -1t "$BACKUP_DIR"/seohealth-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while IFS= read -r f; do
  echo "==> pruning $f"
  rm -f "$f"
done

TOTAL=$(ls -1 "$BACKUP_DIR"/seohealth-*.dump 2>/dev/null | wc -l | tr -d ' ')
echo "==> done — $TOTAL dump(s) retained (keeping newest $KEEP)"
