# SEO Health — Build Roadmap to Launch

*Written 2026-07-08. Sequenced for one owner working with AI assistance,
grounded in the existing backlog (memory notes + `launch_checklist.md` +
`future_additions.md`), not a wishlist. Companion: `ARCHITECTURE.md` for the
why behind each call. Estimates are honest guesses: S ≈ ≤half a day,
M ≈ 1–2 days, L ≈ 3–5 days.*

## Do this first — top 3

1. **Verify + close out the discovery→Places migration.** (S–M, was L)
   *Corrected 2026-07-12: this was written as "not built yet" but commit
   `d5cd81d` (2026-07-07) already contains the complete native engine —
   `services/discovery.py` wired into `discovery_scan_job`, filter DSL
   ported verbatim, Selenium out of requirements, zero remaining callers
   of `competitor_scraper_adapter.py`.* What actually remains: run one
   real scan against live Places and check the SKU report (zero Place
   Details per candidate — the cost trap), then the ranked findings in
   `PLACES_MIGRATION_CLOSEOUT.md` (repo root, local): lazy pagination
   (3× cost saving), `place_id` threaded into results→tracking
   (mis-resolution + cost fix), place_id-based roster dedupe, failed-scan
   quota refund, dead-code deletion.
2. **Finish the IG Graph (Model A) setup.** (S–M, mostly console work)
   Grab the App Secret + long-lived token (Business Verification passed
   2026-06-28), wire `.env`, re-run the Nike `business_discovery` probe,
   confirm a real audit populates the IG pillar and a competitor refresh
   writes follower counts. Without this, one of five pillars reads
   "unavailable" for every user on day one.
3. **A minimal pytest harness around the money-logic.** (M)
   Not coverage theatre — ~25 tests on the four things that keep breaking
   or would be catastrophic: overall-score aggregation rules
   (None-vs-0, opt-outs, the "0s but 85" regression), tier limits + quota
   windows (402/429 shapes), Razorpay webhook transitions (activate /
   cancel / past-due, bad signature), and audit status gating (Maps-failed
   ⇒ audit failed ⇒ quota refunded). Run against SQLite in-memory; add an
   `alembic upgrade head` check against a throwaway Postgres container to
   kill the dev/prod migration drift class. Everything after this gets
   cheaper and safer.

## Phase 1 — Deploy-ready (private beta on the VPS)

*Goal: you + a few invited owners using seohealth.in daily. Roughly a
focused week after the top-3.*

- **Provider accounts + `.env.prod`** (S–M): Resend (verify seohealth.in,
  `FROM_EMAIL=hello@seohealth.in`), Sentry DSN, real `POSTGRES_PASSWORD`,
  `SESSION_COOKIE_SECURE=true`, `APP_BASE_URL` knob for digest links
  (currently a hardcoded default). Razorpay stays empty → mock checkout.
- **Backend rebrand sweep** (S): `from_email` sender name, email templates,
  push payload defaults — frontend is already unified; login deliverability
  rides on the sender identity.
- **Caddy + SSE verification** (S): confirm `/api/audits/*/stream` streams
  unbuffered through Caddy; smoke the reopened-tab replay.
- **First prod boot checklist** (M, mostly waiting): compose up, `alembic
  upgrade head` on Postgres, run one real audit from the VPS, one discovery
  scan, then **check the Places SKU report** — Text Search calls ≈ pages
  fetched, no Place Details fan-out. This is a hard launch gate. Set the
  $10/day billing cap + server-IP key restriction while in the console.
- **Scheduler liveness** (S): run `scripts.run_scheduler` under compose
  (it's already a service in prod compose — verify), and extend `/api/health`
  to report queue depth + last-dispatch timestamp so "cron silently dead"
  is visible from a phone.
- **Backups** (S): nightly `pg_dump` cron + one restore drill. Untested
  backups are theatre.
- **Digest end-to-end** (S): run `dispatch_weekly_digests` manually against
  a real inbox once Resend is live; opt-out toggle already exists.

## Phase 2 — Private-beta hardening (while friends use it)

- **Operational runbook** in `project_notes.md` (S): audits failing → check
  X; emails dead → check Y; funnel stale → the Tailscale note. Cheap now,
  expensive to reconstruct mid-incident.
- **Admin panel glance-ables** (S–M): the founder stats panel exists; add
  the trust signals you'll actually watch — audits/day, failure rate,
  Places call count, insight-report count (most-reported rec = a real bug).
- **In-app notification affordances** from the agreed backlog (M): the
  audit-done banner + push exist; finish the loop the backlog names
  (in-app recap surfacing, audit-done toast) only where the weekly loop
  demonstrably needs it — the status-first home (2026-07-07) already
  covers a chunk of this.
- **Weekly digest idempotency** (S): a `last_digest_sent_at` column the day
  double-sends are observed, not before.

## Phase 3 — Public, paid launch

- **Razorpay live** (M + KYC wait): KYC, create the live Pro plan and the
  **Max plan at ₹1,999 (does not exist yet; amounts immutable — create
  fresh)**, live keys + webhook secret, one real ₹-small end-to-end charge.
- **Legal pages get real content** (M): privacy/terms/refund are
  placeholders by design; finalize via Termly per the deferred plan, flip
  the DPA answers as provider accounts now exist.
- **Marketing site** (S–M): `site/` deploys via Cloudflare Pages — remember
  editing the repo ≠ live; re-deploy. Point it at the app with honest
  screenshots of the shipped product.
- **Analytics** (S): Plausible or PostHog free tier — signups, activation
  (first audit completed), upgrade clicks. The 3 % conversion target from
  the unit-economics note needs a funnel to be measurable.
- **Abuse re-check** (S): rate limits exist on request-link and
  create-business; add one on discovery-scan creation (it's the expensive
  endpoint) — the monthly tier cap already bounds it, this is belt +
  braces for multi-account abuse.

## Phase 4 — Post-launch growth (pull from, don't push)

In rough value order, all grounded in existing notes:

1. **Rank-movement + review-velocity insights** (M): "you passed Kadalas
   Cafe this month", "they gain 12/mo, you gain 4" — the observations are
   already stored; this is deterministic wiring, and it's the strongest
   return-hook upgrade available for the money (see
   `backend/INSIGHTS_ASSESSMENT.md`).
2. **Places autocomplete on Add-business** (M): kills the paste-a-Maps-URL
   friction; needs its own per-IP rate limit before shipping (public,
   billable endpoint).
3. **Zomato/Swiggy pillar** for food businesses (L): highest-leverage new
   pillar for the ICP; slots under `pillar_optout.enabled_pillars`.
4. **Streaks / accumulation surfaces** (M): pick ONE (the external critique
   is right that the dashboard empties between visits) — the weekly-insights
   "effort" beat is the natural home.
5. **Per-business-type scoring weights**: explicitly HOLD (per
   `future_additions.md`) until real usage data exists.

## Explicitly not on the roadmap

- **Residential proxies** — decided dead end; API-first won.
- **More dashboard surfaces** — the product-risk note (scope explosion,
  doom-dashboard) still governs; depth over breadth.
- **LLM-generated recommendations** — evaluated and deleted once already
  (Phase 5.1); the deterministic bodies are the product. The one phrasing
  call stays optional and cached.
- **Horizontal scaling work** (gunicorn multi-worker, Redis-backed limiter,
  multi-VPS) — single box covers launch scale; the two single-process
  assumptions are documented in `ARCHITECTURE.md` for when this changes.

## Stale docs to be aware of (so they don't mislead)

`launch_checklist.md` predates the Places migration: the Chrome-RAM VPS
sizing, proxy planning, "manifest.json missing", digest-opt-out-missing and
rate-limit items are already done or moot. `outflow_integration_specs.md`
is stale on the audit_scraper interface. `AuditAppPlan.md` remains the
best statement of product ethos; its architecture section describes the
pre-Places world. This file + `ARCHITECTURE.md` supersede both on
sequencing and system shape as of 2026-07-08.
