# SEO Health — Build Roadmap to Launch

*Written 2026-07-08. Sequenced for one owner working with AI assistance,
grounded in the existing backlog (memory notes + `launch_checklist.md` +
`future_additions.md`), not a wishlist. Companion: `ARCHITECTURE.md` for the
why behind each call. Estimates are honest guesses: S ≈ ≤half a day,
M ≈ 1–2 days, L ≈ 3–5 days.*

## Do this first — top 3

1. **Discovery→Places migration — CLOSED OUT 2026-07-13 (code + runtime-verified).**
   All eight `PLACES_MIGRATION_CLOSEOUT.md` findings executed: F1+F6 lazy
   pagination (`search_text_pages` generator; a num_leads=5 scan now bills
   **1** Text Search request, not 3), F2 `place_id` threaded discovery→track→
   refresh, F3 place_id-based roster dedupe (catches the `?cid=` regression),
   F4 failed-scan quota refund, F5 dead adapter/config/comments deleted, F8
   verified no dead FE fields. Verified live in-process against real Places:
   **1 Text Search call, 0 Place Details calls, place_id 15/15** — the cost
   guardrail holds. Offline + in-memory-DB tests cover the pagination + dedupe
   logic. **One gate remains, owner-only:** confirm the Cloud Console SKU
   report shows Text Search (Enterprise) ≈ pages fetched and **zero** Place
   Details attributable to discovery (billing-side ground truth for the
   runtime measurement). Optional: full browser render+track E2E (costs a few
   more live calls).
2. **IG Graph (Model A) — DONE 2026-07-13.** Now on a **never-expiring System
   User token** (upgraded from the 2026-06-29 ~60-day user token). App Secret +
   token in `backend/.env`, `ig_token.py` confirmed `SYSTEM_USER` / expires
   never / all 4 scopes; Nike + natgeo + seo.health `business_discovery` probes
   all return `source=graph`, and `audit_instagram` (the single chokepoint for
   both the user's own IG pillar and competitor refresh) returns `source=graph`.
   Workers restarted to load it. The 5th pillar is live for day one, set-and-
   forget (no token-refresh chore).
3. **Money-logic pytest harness — LARGELY DONE 2026-07-13.** `backend/tests/`
   (conftest + 4 suites, 31 passing / 3 tracked skips): overall-score
   aggregation (incl. the "0s but 85" regression), tier limits + quota
   windows (402/429), Razorpay webhook transitions + bad-signature, audit
   status gating (on_failure hook). Also **unified the 5 drifted overall-score
   aggregation sites** into `services/scoring.py` (finding #1) and applied the
   **W2–W5 live-billing fixes** (resurrect-after-cancel guard, cancel-API wired,
   live tier-change blocked 409, total_count 12→120) — all inert in mock mode,
   so the beta is unaffected; they turn "go live" into a config flip.
   `scripts/check_migrations.sh` (alembic vs models vs throwaway Postgres 16)
   **found + fixed two latent prod-fatal migrations** (`has_website = 1` int-for-
   bool; enum `ALTER TYPE` autocommit-in-txn). Remaining: the 3 skipped
   pipeline-integration tests (Maps-spine gate / non-spine soft-fail / carried
   check-marks) need a scraper-mocking harness — deferred, not faked.

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
  fresh; decide ANNUAL plans at the same sitting)**, live keys + webhook
  secret, one real ₹-small end-to-end charge. **Hard gates before going
  live** (found 2026-07-12, details in `MONEY_TESTS_SPEC.md` W2–W5): wire
  the Razorpay cancel API (today in-app cancel doesn't stop billing), guard
  webhook re-activation of cancelled rows, block live tier-changes until
  cancel+recreate exists, and raise `total_count` from 12 (else every
  subscriber silently expires to free at month 12).
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
