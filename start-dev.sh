#!/usr/bin/env bash
# AuditHealth — local dev stack launcher.
#
# Brings up everything the phone PWA needs to be live behind the existing
# Tailscale Funnel: uvicorn (API), the audit + competitor RQ workers, and
# the Vite dev server. Tailscale itself is *not* started here — the daemon
# is configured to auto-start at login, and `tailscale funnel` state is
# persisted by Tailscale across reboots.
#
# Idempotent: any existing instance of each process is killed before
# starting a new one, so re-running the script is safe.
#
# Logs:
#   /tmp/audit_backend.log
#   /tmp/audit_worker.log
#   /tmp/competitor_worker.log
#   /tmp/vite.log
#   /tmp/start-dev.log  (this script's own boot log)
#
# Usage:
#   ./start-dev.sh              # foreground messages, processes backgrounded
#   ./start-dev.sh --quiet      # boot silently (suitable for Login Item)

set -u

REPO_DIR="/Users/adwaithjayakrishnan/Desktop/AuditHealth app"
BACKEND_DIR="$REPO_DIR/backend"
FRONTEND_DIR="$REPO_DIR/frontend"
BOOT_LOG="/tmp/start-dev.log"

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=1
fi

log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" >> "$BOOT_LOG"
  if [[ $QUIET -eq 0 ]]; then
    echo "$msg"
  fi
}

# --- guard: bail early if the backend venv isn't set up -------------------
if [[ ! -f "$BACKEND_DIR/.venv/bin/activate" ]]; then
  log "ABORT: backend venv missing at $BACKEND_DIR/.venv — run \`python -m venv .venv && pip install -r requirements.txt\` first"
  exit 1
fi
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  log "ABORT: frontend node_modules missing — run \`npm install\` in $FRONTEND_DIR first"
  exit 1
fi

log "==== boot start-dev.sh (quiet=$QUIET) ===="

# --- kill any existing instances ------------------------------------------
# pkill exit codes: 0=killed, 1=no match. Either is fine here.
pkill -f "uvicorn.*app.main"          >/dev/null 2>&1 || true
pkill -f "scripts.run_worker"         >/dev/null 2>&1 || true
pkill -f "scripts.run_competitor_worker" >/dev/null 2>&1 || true
# Vite is just `node vite` — narrow the pattern so we don't kill unrelated node processes.
pkill -f "node .*vite" >/dev/null 2>&1 || true

# Give them a moment to release ports / RQ heartbeats.
sleep 2

# --- start uvicorn (with --reload so future edits hot-load) ---------------
(
  cd "$BACKEND_DIR"
  source .venv/bin/activate
  nohup uvicorn app.main:app --port 8000 --host 127.0.0.1 --reload \
    > /tmp/audit_backend.log 2>&1 &
)
log "started uvicorn on :8000"

# --- start audit RQ worker (SimpleWorker on macOS — see dev_workflow_workers memory) ---
(
  cd "$BACKEND_DIR"
  source .venv/bin/activate
  nohup python -m scripts.run_worker > /tmp/audit_worker.log 2>&1 &
)
log "started audit worker"

# --- start competitor RQ worker ------------------------------------------
(
  cd "$BACKEND_DIR"
  source .venv/bin/activate
  nohup python -m scripts.run_competitor_worker > /tmp/competitor_worker.log 2>&1 &
)
log "started competitor worker"

# --- start Vite -----------------------------------------------------------
# vite.config.js binds to 127.0.0.1 — Tailscale Funnel proxies to it.
(
  cd "$FRONTEND_DIR"
  nohup npm run dev > /tmp/vite.log 2>&1 &
)
log "started vite on :5173"

# --- wait a few seconds and verify ----------------------------------------
sleep 5

ok=1
if ! lsof -i :8000 >/dev/null 2>&1; then
  log "WARN: nothing listening on :8000 — check /tmp/audit_backend.log"
  ok=0
fi
if ! lsof -i :5173 >/dev/null 2>&1; then
  log "WARN: nothing listening on :5173 — check /tmp/vite.log"
  ok=0
fi
if ! pgrep -f "scripts.run_worker" >/dev/null 2>&1; then
  log "WARN: audit worker isn't running — check /tmp/audit_worker.log"
  ok=0
fi
if ! pgrep -f "scripts.run_competitor_worker" >/dev/null 2>&1; then
  log "WARN: competitor worker isn't running — check /tmp/competitor_worker.log"
  ok=0
fi

if [[ $ok -eq 1 ]]; then
  log "==== all four processes up — PWA should be live ===="
else
  log "==== some processes failed — see warnings above ===="
  exit 1
fi
