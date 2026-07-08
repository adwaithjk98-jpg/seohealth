# Intelligence Layer — Assessment & Changes (2026-07-08)

## What "good" means here (the bar)

A good SEO Health insight is a sentence the owner couldn't have written from
the raw numbers alone, but can immediately verify against them: it names the
*specific* thing (a rival, a gap, a date), says which way it's moving, and
points at most one place to act — in a calm second-person voice. A generic
insight restates the dashboard ("your rating is above average"); a risky one
asserts what the data doesn't hold ("steady" over a real drop, a café example
handed to a chemicals supplier). The product's promise is *insight, not
graphs* — so the words must add information, never decorate it.

## Assessment of what was there

**The architecture is right and stays.** Every number in every surface is
computed deterministically; the only LLM call in the codebase
(`competitor_insights._llm_sentence`, Claude Haiku 4.5) is a phrasing layer
downstream of a pre-decided fact, with a hand-written fallback. That's the
correct shape for a trust product and I did not change it. Also already
good: the recommendation bodies (WHY/HOW with numbered, verifiable steps),
the `section_highlight` delta headlines, the weekly-report beat structure,
and the matched-threshold guard that kills "4.3★ is below … 4.3★" cards.

**What was weak, with evidence:**

1. **The competitor sentence restated the card.** The card already shows the
   value, the average, and the rival names; the sentence added nothing:
   > *"Your review count (199) is sitting above the 2 competitors you're
   > tracking, who average 48."*
   Worse, "above the average" can be true while a rival is still ahead —
   the average hid the one fact an owner cares about (who's next, how far).
2. **The dormant LLM path had no cache and the wrong voice.** It fired on
   every hub page-load (2 calls/visit — pure cost and ~seconds of latency
   once a key lands), and its prompt demanded the business be referenced by
   name — clashing with the app's universal "you/your" voice.
3. **A white lie in the weekly report.** With `reviews_delta = -1` the growth
   beat rendered *"steady since we started watching"*. Review counts really
   do fall (Google prunes); "steady" over a −20 would have been a trust hole.
4. **A paywall pointer disguised as content.** The free-tier dip lead said
   *"there's one clear move to turn it around below"* — and "below" is
   exactly the beat free users see locked.
5. **Generic filler in the flagship rec.** The meta-description fix showed
   every business the same café example ("single-origin coffee and fresh
   bakes") — including B2B suppliers. The FTUE already collects
   `business_type`; the copy just never used it.
6. Stale brand ("your AuditHealth profile") inside the IG-mismatch rec body.

## What changed

- **`competitor_insights.py`** — facts now carry *named* rival context, all
  deterministic: nearest rival above (the next target), nearest below (the
  chaser), and how many of N the user beats. Both the deterministic
  sentences and the LLM prompt use them; the LLM prompt also switched to
  second person, got hard no-hype/no-alarm rules, `temperature=0.2`,
  and an `lru_cache` so identical facts stop re-billing per page-load.
  Every phrasing branch is exercised below.
- **`weekly_insights.py`** — free-tier dip sub no longer points at the
  locked beat ("one focused fix usually brings it right back").
- **`weekly-insights/+page.svelte`** — growth beat now says "N fewer than
  last check" / "down N since we started watching" when that's what the
  data says.
- **`scrapers/website.py` + `types.py` + `audit_runner.py`** —
  `business_type` now travels with the audit input; the meta-description
  example is type- and city-specific; brand mention fixed.

## Before → after (real data, deterministic path)

| Case | Before | After |
|---|---|---|
| Leads all rivals (real: Lead chem industries) | "Your review count (199) is sitting above the 2 competitors you're tracking, who average 48." | "Your review count (199) leads all 2 competitors you're tracking — The Travancore Cochin Chemicals is closest at 50." |
| Behind all rivals | "Your average rating (4.1★) is currently below the 2 competitors you're tracking, who average 4.5★." | "Your average rating (4.1★) trails the 2 competitors you're tracking — the nearest, Kadalas Cafe, is at 4.4★." |
| Above average but a rival ahead | "…is sitting above the 2 competitors you're tracking, who average 80." *(hid the rival ahead)* | "Your review count (100) is above the average of the 2 competitors you track, though Big Rival is still ahead at 150." |
| Middle of the pack | *(read as generically "below")* | "Your review count (120) is ahead of 2 of the 3 competitors you track — the next target is Leader Cafe at 300." |
| Reviews fell by 1 (real: 199→) | "**steady** since we started watching." | "1 fewer than last check · down 1 since we started watching." |
| Meta-description rec for a supplier | e.g. "Cosy specialty café in Calicut serving single-origin coffee and fresh bakes." | e.g. "Trusted wholesale supplier in Kochi — quality stock, dependable delivery." |

## Deliberately left alone

The deterministic-first architecture; tier gating (who sees which beats is
untouched); the recommendation WHY/HOW bodies (already specific and honest);
`section_highlight`; `audit_summary` sub-checks; the weekly digest email
(it reuses the report's lead verbatim — improvements flow through); the
Haiku model choice (right tier for one-sentence phrasing; per the
`claude-api` reference, Haiku 4.5 remains the current small model).

## Honest notes

- **The LLM path is still dormant** — no `ANTHROPIC_API_KEY` in `.env`, so
  production output today is the deterministic fallback (which is why it got
  the same specificity upgrade). When a key lands, spot-check a dozen live
  sentences against the facts before trusting it; the cache means a bad
  sentence sticks until the numbers move or the process restarts.
- **RQ workers don't auto-reload** — the `business_type` threading through
  `audit_runner` reaches real audits only after a worker restart (dev-stack
  memory note applies).
- **What the insights *want* to say but the data can't yet support:** rank
  *movement* ("you passed Kadalas Cafe this month" — needs comparing two
  observation snapshots, all stored, just not wired), review *velocity*
  ("they're gaining 12/month, you're gaining 4" — same), and category-aware
  benchmarks ("good for a salon in Kochi" — needs a cohort we don't have).
  First two are cheap deterministic follow-ups; noted for the roadmap.
