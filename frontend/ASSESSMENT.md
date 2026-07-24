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
   **[Brand name ✅ resolved: manifest/title/apple-touch title, account support
   email (`hello@seohealth.in`) and export filename (`seohealth-export-…`) all
   read "SEO Health" as of the 2026-07-24 rebrand sweep. The non-brand sub-items
   here (landing "Free during the beta" copy, per-route `<title>`s) are tracked
   separately and NOT covered by that sweep.]**
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

---

## What actually changed (changelog, in commit order)

1. **Bug fixes** (`977e15f`) — invisible Weekly-Insights trajectory bars
   (percentage heights in auto-height flex columns → explicit px); ScoreGauge
   said the trend direction twice; "Your four health pillars" hardcoded while
   five render; business h1 greeted the cafe instead of the owner; audit-done
   banner whitespace ("in— checked"); `inline code` in recommendation bodies
   rendered as literal backticks; deleted unused `CompetitorsSection.svelte`.
2. **One name everywhere** (`2b60f75`) — SEO Health across html title,
   apple-touch title, PWA manifest, header, billing card, Razorpay checkout
   label, account About, export filename, SW cache prefix, legal name
   mentions. Every route now sets a real `<title>`. Landing pill no longer
   claims "Free during the beta"; support address is hello@seohealth.in.
3. **Status-first home** (`ff7168d`) — single-business users (every Free/Pro
   account) open to a hero card: score ring + trend delta, "since your last
   check" line, tinted pillar chips, tap-through to the full view; a "your one
   move this week" card deep-links the top fix; Weekly-Insights + all-insights
   fold into one row. Running audit → live-watch hero; no audit yet → first
   check starts from the home. Multi-business keeps the grid with an
   aggregate header line. One bounded latest-audit fetch in `+page.js`,
   graceful fallback to the old card view on failure.
4. **Mobile bottom tab bar** (`e1e8bd6`) — persistent Home/Audits/Competitors
   on every signed-in surface below `sm`, safe-area aware; desktop keeps the
   dashboard pill; header home icon hidden on mobile; discover toast lifted
   above the bar; "Back to your businesses" → "Back home".
5. **One canonical dashboard + palette + dead-loop fix** (`b346d60`) —
   `/audits/{id}/dashboard` (280-line drifting copy of `/businesses/{id}`)
   is now a redirect that keeps old bookmarks alive; live-audit screen links
   straight to the business view. Chart lines now use the app's actual
   tokens (sage, not Tailwind emerald). "Run a health check" on a no-audit
   business no longer bounces through "/" back to the dashboard — it starts
   the audit directly.

**Verification**: `npm run build` passes; `svelte-check` went from 138
pre-existing errors to 124 (nothing added, duplicate page's noise removed);
every flow re-clicked at 390×844 (home single+multi, business, section +
finding modal, redirect, weekly insights, competitors, billing, landing).

## Honest notes / what I'd do next

- **svelte-check is not green and never was** — 124 pre-existing type errors
  remain (mostly `any`-indexing in older pages). Worth a dedicated pass.
- **Backend gaps designed around**: none of this pass depends on new backend;
  the home hero reuses the existing latest-audit endpoint. The Places
  migration branch's backend changes are untouched and uncommitted, as found.
- **Legal pages** got a brand-name swap only; the policies are still
  placeholders and still need real content before launch.
- **`.prose` classes in FindingModal do nothing** (no typography plugin
  installed) — harmless today because the structured WHY/HOW path renders
  first; either install the plugin or drop the classes.
- **Next, in order of value**: (1) surface the trajectory sparkline on the
  home hero too, (2) a real `<meta name="description">` + OG tags for the
  landing, (3) type-error cleanup pass, (4) consider tinting indigo/sky
  competitor chart hues toward the brand once there are ≥3 competitors in
  the wild to test separability.
