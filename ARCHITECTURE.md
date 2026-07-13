# SEO Health — Architecture Map & Health Assessment

*Written 2026-07-08 after a full read of `backend/app`, `backend/scrapers`, the
frontend consumption layer, and the operational scripts. Companion to
`ROADMAP.md`. Pre-launch, mid-build — judged against "what will carry a
launch on a small VPS", not perfection.*

## The system in one paragraph

A SvelteKit static-adapter PWA talks to a FastAPI backend (`/api/*`) through
a dev proxy / prod reverse-proxy. Writes that take time (audits, discovery
scans) are enqueued to **RQ on Redis** and executed by separate worker
processes; the live audit screen follows progress over **SSE backed by Redis
Streams** (replayable, 24 h TTL, guaranteed-terminal via RQ's `on_failure`
hook). **SQLAlchemy + Alembic** over SQLite in dev / Postgres in prod.
`rq-scheduler` is the cron clock: hourly auto-audit dispatch (spread by
`id % 24` buckets), weekly competitor refresh, weekly digest, daily pruning
of >30-day `raw_data_json`. Auth is magic-link → HttpOnly session cookie.
Payments are Razorpay subscriptions with an HMAC-verified webhook and a mock
checkout fallback when keys are absent.

```
Browser (PWA) ──/api──> FastAPI ──enqueue──> Redis ── RQ ──> audit worker ──┐
     ▲                    │  ▲                (2 queues)      competitor    │
     │ SSE (Redis Stream) │  │                                 worker       │
     └────────────────────┘  └── SQLAlchemy ── SQLite/Postgres <────────────┘
                                                    ▲
              rq-scheduler (hourly/daily/weekly crons) ┘
Data sources: Places API (New) · PageSpeed API · IG Graph business_discovery
              · plain httpx website fetch — no browser anywhere
              (discovery is native Places as of 2026-07-13)
```

## What's genuinely solid (don't churn this)

- **The audit pipeline state machine** (`services/audit_runner.py`). Honest
  scoring rules are encoded and commented (`score=None` = unmeasurable →
  excluded from the average; `score=0` = measured bad → included; audit only
  `done` if Maps — the spine — loaded). Quota refunds on failure, carried
  "done" check-marks, fix verification (`verify_signal`), per-section
  live-diff highlights, FTUE pillar opt-outs persisted as placeholders.
  This is the most battle-hardened code in the repo.
- **The queue/event topology.** Two queues (`audits`, `competitor_jobs`)
  keep a batch discovery scan from starving a live audit; discovery jumps
  its own queue (`at_front`) for the user who clicked. The stream key is
  created *before* enqueue so a fast SSE subscriber can't race the worker;
  `on_audit_job_failure` is a correct last line of defence against
  OOM/SIGKILL leaving rows stuck at `running`.
- **The Maps→Places migration is done for the audit path** (`scrapers/maps.py`
  + `places.py`): place_id pinning with self-heal, field masks pinned to the
  Enterprise-tier fields the product uses, review *text* deliberately never
  requested, per-listing = exactly one call. Cost-consciousness is written
  into the module docstrings.
- **Deterministic-first intelligence layer** (see
  `backend/INSIGHTS_ASSESSMENT.md`): every number computed from stored data;
  the one LLM call is phrasing-only with a hand-written fallback.
- **Tier enforcement lives server-side** (`services/subscriptions.py`
  TIER_LIMITS + 402/429 structured errors) and the frontend mirrors it for
  UX only. Gates test `== free`, not `!= paid` (the Max-tier lesson).
- **Operational shape**: dev/prod docker-compose with separate `api`,
  `worker`, `competitor-worker`, `scheduler` services; Sentry wired but
  dormant; slowapi rate limits on the two abuse-prone endpoints
  (`request-link`, `POST /businesses`); daily prune keeps Postgres flat.

## What's fragile (ranked by how hard it bites)

1. ~~Discovery ran a forked Selenium engine as a subprocess.~~
   **✅ RESOLVED 2026-07-13.** Discovery is now the native Places
   `search_text_pages` engine (`services/discovery.py`); the adapter and
   `AUDIT_SCRAPER_PATH` config are deleted — no Chrome, no second repo, no
   separate venv on the VPS. Closed out per `PLACES_MIGRATION_CLOSEOUT.md`
   (F1–F8) and verified live (1 Text Search call, 0 Place Details, place_id
   15/15). Only the owner's Cloud Console SKU-report confirmation remains.
   *(The current biggest gap is now #2, the missing test suite.)*
2. **No automated test suite.** Only manual scripts (`scripts/test_*.py`).
   The regression-prone money-logic — overall-score aggregation (the
   recurring "0s but 85 overall" bug), tier limits, weekly quota windows,
   webhook state transitions — is protected by nothing but care. This is
   the cheapest insurance not yet bought, and it compounds: every later
   roadmap item gets safer once it exists.
3. **Instagram depends on Graph API config that isn't finished.** Model A
   (`business_discovery`, single token, no App Review) is implemented and
   the instagram.com scraper fallback is deliberately off — correct for a
   server — but the token/App-Secret setup is pending. Until then the IG
   pillar reports "unavailable" and competitor IG trends stay flat.
4. **Dev/prod database split** (SQLite dev, Postgres prod). Alembic
   migrations have already bitten once (the push-500 stale-migration
   incident). Nothing continuously verifies `alembic upgrade head` against
   Postgres; the first prod boot will be the test.
5. **Single-process assumptions**: the slowapi limiter stores counters
   in-memory (documented; breaks silently behind gunicorn multi-worker),
   and the new insight-sentence LRU cache is per-process. Both are fine for
   the 1-vCPU single-uvicorn deployment — they're listed here so scaling
   up doesn't silently disable rate limiting.
6. **SSE through a reverse proxy** is a classic silent killer: Caddy must
   not buffer `/api/audits/*/stream`, and the Redis stream key has a 24 h
   TTL (a tab reopened later replays only if the audit is < 24 h old — the
   terminal-probe in the frontend covers the rest, but verify on prod).
7. **Backend brand is still AuditHealth** in `from_email`, email templates
   and assorted strings (frontend was unified to SEO Health on 2026-07-07).
   Login = email deliverability, so the sender identity matters at deploy.
8. **Weekly digest has no idempotency table** (documented contract: cron
   once, accept double-send risk) and `dashboard_base_url` needs the prod
   config knob before real users receive one.

## Traps to respect (things that will silently hurt)

- **Places bills per *request*, not per result.** Discovery must read
  rating/review_count/website from the Text Search field mask (20/page, ≤60)
  and reject candidates in memory — never a per-candidate Place Details
  loop. Verify in the Cloud Console SKU report at launch (hard gate; also
  budget the 18 % GST — ₹1.77/call, not ₹1.50).
- **RQ workers don't hot-reload.** uvicorn/vite do; worker-code edits go
  stale until the worker restarts (macOS dev uses SimpleWorker). Half the
  "my fix didn't work" incidents trace here.
- **rq-scheduler persists schedules in Redis** — the startup cancel-then-
  re-add dance in `run_scheduler.py` is load-bearing; a second scheduler
  process would double-fire crons.
- **The scheduler is a separate process.** Forget to run it on the VPS and
  auto-audits, digests, pruning and competitor refresh all silently stop.
  A `/status` route asserting "scheduler heartbeat seen recently" is cheap.
- **Razorpay plan amounts are immutable** — the live Max plan (₹1,999) must
  be created fresh (it does not exist yet); the code's price labels already
  assume it.
- **seohealth.in renews manually ~May 2027** (BigRock, no UPI auto-renew).

## Where the 1-vCPU VPS actually stands

Better than the older docs suggest. The audit path is now pure async HTTP
(Places, PageSpeed, Graph, httpx) — no Chrome, so the old "2 GB will OOM
mid-audit" and proxy-cost warnings in `launch_checklist.md` are stale for
audits. CPU load is I/O-bound waiting, and the hourly `id % 24` bucketing
spreads scheduled audits. Discovery is now native Places too (no Chrome
anywhere as of 2026-07-13), so nothing heavyweight remains: the whole stack
(api + 2 workers + scheduler + Postgres + Redis + Caddy) fits the box with
room; the realistic ceiling becomes
Postgres connections and PageSpeed API latency, neither of which matters at
launch scale.
