#!/usr/bin/env bash
# SEO Health — persistent self-heal watchdog for the dev stack + Tailscale funnel.
#
# Launched as a SINGLETON by start-dev.sh (which runs from the macOS Login
# Item), so it lives in your GUI login session and inherits its file-access
# permissions. A launchd LaunchAgent can't do this job: the repo lives under
# ~/Desktop, which macOS TCC blocks launchd-spawned processes from touching
# ("Operation not permitted").
#
# Every 120s it:
#   1. Checks the five stack processes; relaunches the stack if any is down.
#   2. Checks the Tailscale funnel's PUBLIC edge; resets it if it went stale
#      (the announcement drops on sleep/wake — the "site can't be reached"
#      even though the local stack is fine).
set -u

REPO_DIR="/Users/adwaithjayakrishnan/Desktop/AuditHealth app"
GUARD_LOG="/tmp/audithealth-guard.log"
FUNNEL_HOST="adwaiths-macbook-air.taileffa22.ts.net"
# Public resolvers, tried in order. 1.1.1.1 on its own was a single point of
# failure: it is blackholed on both networks this laptop actually lives on
# (campus wifi and the phone hotspot), so the lookup below returned nothing,
# the "can't resolve -> assume ok" guard fired on every cycle, and the funnel
# self-heal never ran once. The failure it exists to catch had to be spotted
# by hand instead.
FUNNEL_RESOLVERS="1.1.1.1 8.8.8.8 9.9.9.9"
TAILSCALE="/usr/local/bin/tailscale"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
listening() { /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
running()   { /usr/bin/pgrep -f "$1" >/dev/null 2>&1; }

stack_ok() {
  # The scheduler is checked here too. Without it the cron clock could die and
  # stay dead indefinitely while every other process looked fine — auto-audits,
  # the weekly digest and the competitor refresh would silently stop and
  # nothing would ever say so. That is not hypothetical: it had not been
  # started at all for weeks.
  listening 8000 && listening 5173 \
    && running "scripts.run_worker" && running "scripts.run_competitor_worker" \
    && running "scripts.run_scheduler"
}

funnel_ok() {
  # MagicDNS short-circuits to the tailnet IP from this Mac, so a plain curl
  # always 200s even when the funnel is broken upstream. We must probe a real
  # PUBLIC ingress edge — resolve the funnel host via a public resolver and try
  # each edge IP. Healthy if ANY edge answers (incl. a 502, which means the
  # edge is up and the stack check handles the rest).
  local ips ip r
  # Try each public resolver, then fall back to the system one. Tailnet
  # answers (CGNAT 100.64.0.0/10) are dropped: with MagicDNS on, a resolver
  # reached through the tunnel can hand back the tailnet address, and probing
  # that would test the local stack instead of the public ingress — passing
  # happily while the funnel is down.
  for r in $FUNNEL_RESOLVERS ""; do
    ips=$(/usr/bin/dig +short +time=3 +tries=1 ${r:+@"$r"} "$FUNNEL_HOST" 2>/dev/null \
      | /usr/bin/awk -F. '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ &&
                          !($1 == 100 && $2 >= 64 && $2 <= 127) { print }')
    [ -n "$ips" ] && break
  done
  # Only now is it genuinely unresolvable — every resolver failed, so the box
  # has no working DNS at all and resetting the funnel would not help.
  [ -z "$ips" ] && return 0   # can't resolve → don't thrash; assume ok
  for ip in $ips; do
    if /usr/bin/curl -sS --resolve "$FUNNEL_HOST:443:$ip" -o /dev/null \
         --max-time 8 "https://$FUNNEL_HOST/" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

echo "[$(ts)] watchdog started (pid $$)" >> "$GUARD_LOG"

while true; do
  if ! stack_ok; then
    echo "[$(ts)] stack unhealthy — relaunching via start-dev.sh --no-watch" >> "$GUARD_LOG"
    "$REPO_DIR/start-dev.sh" --no-watch --quiet
  fi

  if ! funnel_ok; then
    echo "[$(ts)] funnel stale — resetting" >> "$GUARD_LOG"
    "$TAILSCALE" funnel reset >/dev/null 2>&1
    sleep 2
    "$TAILSCALE" funnel --bg 5173 >/dev/null 2>&1
  fi

  sleep 120
done
