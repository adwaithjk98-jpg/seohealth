# Frontend Assessment — SEO Health (frontend redesign pass, 2026-07-07)

## What this product is (in my own words)

SEO Health is **visibility intelligence for Indian small-business owners** — the café,
salon, or clinic owner who isn't technical, doesn't know what a meta description is,
and either ignores their online presence or pays an agency they don't trust. The app
quietly watches how their business looks online (Google Maps, website, Instagram,
NAP consistency, site speed), scores it 0–100, and tells them the **one next concrete
thing to do** in plain, warm English. History is the product: the score over time,
"since your last check", the weekly recap. The emotional job is *reassurance* —
"Apple Watch for your business's online presence", never a doom dashboard.

The person who returns weekly opens the app to answer three questions in order:
**Am I fine? Did anything change? Is there one thing worth doing?** Everything else
(pillar deep-dives, competitor tracking, market charts) is opt-in depth below that.

Tiers: Free (2 audits/week, the score), Pro ₹549 (the watching: auto-audits,
competitors, weekly insights), Max ₹1,999 (Pro turned up, 5 businesses). The upgrade
surfaces are deliberately quiet — a product rule, not an accident.

## Honest assessment of the current frontend

### What's already good — and stays

This is **not** a prototype. The component fabric is genuinely strong and most of it
should not be touched:

- **A coherent design system**: the calm healthy/attention/action/canvas palette, one
  card language, pill badges, soft shadows, a consistent type scale. It reads as one hand.
- **Edge states are covered everywhere**: skeletons with `aria-busy`, friendly error
  cards with retry, "populated" empty states, an offline banner backed by a real
  service worker. Reduced motion is handled centrally (`motion.js` + CSS gates).
- **The live-audit SSE screen** — the product's magic moment — is thoughtfully built
  (stall detection, first-audit reveal, live-diff highlights, terminal-state probe).
- **The finding modal** (why → impact/time/difficulty → numbered how-to → mark done →
  report-this-insight) is the best surface in the app. Leave it alone.
- **Competitor surfaces** (hub with insight cards, 1-by-1 discovery review, market
  matrix) match the "premium" bar the old gap-analysis doc asked for. That doc is stale.
- **The connective tissue**: 409 recovery onto running audits, history-aware back
  buttons, banner-once localStorage logic, tier gates that mirror the server.

### What's weak — and why I'm changing it

1. **The home doesn't serve the weekly loop.** `/dashboard` is a "pick a business"
   index even when the user has exactly one business — which is *every* Free and Pro
   user (1-business cap). A returning owner opens the app and sees: greeting →
   Weekly-Insights pill → an insights-count card → a business card → an upsell. The
   answer to "am I fine?" (score, trend, what changed) is a tap away. This is the
   single biggest gap versus the product's own Layer-1 "glance" spec.
2. **No persistent navigation on mobile.** The Overview/Audit/Competitors pill only
   exists inside `/dashboard/*`; drill into a business, audit, or finding and all
   wayfinding reduces to a small header icon. On the primary device (a phone, often
   installed as a PWA) the app doesn't feel like an app — it feels like pages.
3. **Real bugs**: the Weekly Insights trajectory chart renders **zero-height bars**
   (`items-end` on the row makes the percentage heights resolve against auto-height
   columns) — the page's return-hook is invisible. "Your four health pillars" is
   hardcoded while five pillars render. The score-gauge trend reads "↘ Down · Down 3
   from last check" (says it twice). The audit-done banner renders "in— checked"
   (collapsed whitespace).
4. **Identity drift**: "SEO Health" (mobile header) vs "Local SEO Health" (desktop
   header) vs "Local SEO Health Monitor" (title/manifest) vs "AuditHealth" (billing,
   account, legal, export filename, apple-touch title). The rebrand decision is made
   (seohealth.in, hello@seohealth.in); the code just hasn't caught up. Also stale:
   "Free during the beta" on the landing (there are paid tiers), placeholder support
   email `hello@yourdomain.in`, and almost no per-route `<title>`s.
5. **A 280-line near-duplicate**: `/audits/[id]/dashboard` is a drift-prone copy of
   `/businesses/[id]` (it already misses the since-last-check strip the other has).
6. **Small tone slip**: "Hello, Brewmorphia Cafe 👋" greets the *cafe*, not the owner.

## The plan (proportional response)

Two hero moves, then surgical fixes. No ground-up redesign — the system is good;
the *shape of the loop* is what needs work.

**A. Status-first home (hero surface).** Single-business users get the answer on
open: a hero card with the score ring, trend, "what changed" line, pillar mini-chips,
and the one move this week — tap-through to the full business view. Multi-business
(Max) users keep the grid, led by a compact aggregate strip. The Weekly-Insights
entry and insights count fold into this hierarchy instead of stacking as three
sibling cards.

**B. App-grade wayfinding on mobile.** A fixed bottom tab bar (Home / Audits /
Competitors), visible on all authed app surfaces on small screens, with safe-area
padding — the dashboard-only top pill remains on `sm+`. Deep pages stop being
dead-ends on a phone.

**C. Fixes & coherence (each small, each real):**
- Fix the invisible trajectory bars; dynamic pillar-count heading; de-duplicate the
  trend chip; fix banner whitespace.
- Rebrand sweep to **SEO Health** everywhere (title, manifest, billing, account,
  legal titles, export filename), real support email, retire "beta" copy,
  per-route page titles.
- `/audits/[id]/dashboard` becomes a redirect to the canonical `/businesses/[id]`
  (bookmarks keep working — non-negotiable #3), removing the duplicate.
- Rehome the business-page header copy to address the owner.
- Brand-tint the trend-chart palette (solid line goes sage, not emerald).
- Delete unused `CompetitorsSection.svelte`.

**Deliberately left alone**: live-audit screen, section detail, finding modal,
discovery flow, market matrix, billing switcher, account page, auth flow, tier
gating, loaders/API layer, legal *content* (name swap in titles only), the
marketing site in `site/`.
