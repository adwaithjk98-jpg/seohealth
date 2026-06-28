"""Site-speed / Core Web Vitals scraper, backed by Google PageSpeed Insights.

This is the only audit pillar that measures *how the site performs* rather
than what's in its markup. It's a plain HTTPS call to the PageSpeed Insights
(PSI) REST API — Google runs Lighthouse on their own infrastructure and hands
back JSON, so there is **no headless browser on our box** (the whole reason
this pillar is cheap to run alongside the rest of the audit).

What we surface:
- **Lab score** — Lighthouse's 0–100 performance score (mobile strategy by
  default; local-business traffic is overwhelmingly mobile).
- **Core Web Vitals (lab):** LCP, CLS, TBT (TBT is the lab proxy for INP /
  responsiveness).
- **Field data (real users)** when Google has enough Chrome UX Report (CrUX)
  traffic for the origin — LCP / CLS / INP as actual visitors experience them.

Failure handling mirrors the other scrapers' contract in one important way:
a *successful measurement* always returns an integer score. Anything that
makes the measurement impossible (no URL on file, PSI timeout, quota, 5xx)
**raises** — the audit runner then persists the section as ``failed`` with a
``None`` score, which keeps a transient Google outage from unfairly dragging
the user's overall score down (a ``None`` section is excluded from the mean,
a ``0`` section is not).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from scrapers.types import BusinessInput, ProgressCb, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Core Web Vitals "good" thresholds (Google's published cutoffs).
LCP_GOOD_MS = 2500.0      # Largest Contentful Paint
CLS_GOOD = 0.1            # Cumulative Layout Shift (unitless)
TBT_GOOD_MS = 200.0       # Total Blocking Time (lab proxy for INP)
INP_GOOD_MS = 200.0       # Interaction to Next Paint (field only)


class PageSpeedUnavailable(RuntimeError):
    """We could not obtain a PageSpeed measurement (no URL, timeout, quota,
    upstream 5xx). Raised so the runner records ``failed`` / ``None`` rather
    than a misleading 0 that would drag the overall score."""


async def audit_pagespeed(
    business: BusinessInput, *, progress: ProgressCb = None
) -> SectionResult:
    """Measure the business website's speed via PageSpeed Insights.

    ``progress`` (optional) lets the live-analysis feed narrate the wait —
    a PSI call routinely takes 10–30s while Google runs Lighthouse.
    """
    if not business.website:
        # Performance is gated on the website pillar being enabled, so this
        # only fires for a "has a website but no URL on file" edge. The
        # website pillar already owns the "add your website" nudge; raise so
        # we don't duplicate it or drag the score with a phantom 0.
        raise PageSpeedUnavailable("no website URL on file to measure")

    url = _normalize_url(business.website)
    _emit(progress, "measuring", {"url": url})

    params: dict[str, str] = {
        "url": url,
        "strategy": settings.pagespeed_strategy,
        "category": "performance",
    }
    if settings.pagespeed_api_key:
        params["key"] = settings.pagespeed_api_key

    try:
        async with httpx.AsyncClient(
            timeout=settings.pagespeed_timeout_seconds,
            headers={"Accept": "application/json"},
        ) as client:
            resp = await client.get(PSI_ENDPOINT, params=params)
    except httpx.HTTPError as exc:
        raise PageSpeedUnavailable(f"PageSpeed request failed: {exc}") from exc

    if resp.status_code != 200:
        # 429 = quota; 4xx = bad/unreachable URL Google couldn't analyze;
        # 5xx = Google-side. None is the user's fault, so don't score it 0.
        detail = _error_detail(resp)
        raise PageSpeedUnavailable(
            f"PageSpeed returned HTTP {resp.status_code}: {detail}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise PageSpeedUnavailable(f"PageSpeed returned invalid JSON: {exc}") from exc

    raw = _parse_psi(data, url)
    _emit(progress, "measured", {"performance_score": raw.get("performance_score")})

    score = raw.get("performance_score")
    if score is None:
        # Lighthouse couldn't compute a lab score (rare — usually a page that
        # errored on Google's side). Treat as unmeasurable rather than 0.
        raise PageSpeedUnavailable("PageSpeed did not return a performance score")

    recommendations = _recommendations(raw)
    # ``done`` when we have a full lab result; ``partial`` if Lighthouse gave
    # a score but no Core Web Vitals (very short/blocked pages).
    has_vitals = raw.get("lcp_ms") is not None or raw.get("cls") is not None
    status = "done" if has_vitals else "partial"
    return SectionResult(
        score=score,
        status=status,
        raw_data=raw,
        recommendations=recommendations,
    )


# --- parsing -----------------------------------------------------------------


def _parse_psi(data: dict[str, Any], url: str) -> dict[str, Any]:
    lhr = data.get("lighthouseResult") or {}
    audits = lhr.get("audits") or {}
    categories = lhr.get("categories") or {}

    raw: dict[str, Any] = {
        "url": url,
        "final_url": lhr.get("finalUrl") or data.get("id") or url,
        "strategy": settings.pagespeed_strategy,
        "loaded": True,
    }

    perf = (categories.get("performance") or {}).get("score")
    raw["performance_score"] = round(perf * 100) if isinstance(perf, (int, float)) else None

    # --- lab Core Web Vitals ---
    lcp_ms = _audit_numeric(audits, "largest-contentful-paint")
    raw["lcp_ms"] = lcp_ms
    raw["lcp_display"] = _audit_display(audits, "largest-contentful-paint")
    raw["lcp_good"] = lcp_ms is not None and lcp_ms < LCP_GOOD_MS

    cls = _audit_numeric(audits, "cumulative-layout-shift")
    raw["cls"] = cls
    raw["cls_display"] = _audit_display(audits, "cumulative-layout-shift")
    raw["cls_good"] = cls is not None and cls < CLS_GOOD

    tbt_ms = _audit_numeric(audits, "total-blocking-time")
    raw["tbt_ms"] = tbt_ms
    raw["tbt_display"] = _audit_display(audits, "total-blocking-time")
    raw["tbt_good"] = tbt_ms is not None and tbt_ms < TBT_GOOD_MS

    raw["fcp_ms"] = _audit_numeric(audits, "first-contentful-paint")
    raw["fcp_display"] = _audit_display(audits, "first-contentful-paint")
    raw["speed_index_ms"] = _audit_numeric(audits, "speed-index")
    raw["tti_ms"] = _audit_numeric(audits, "interactive")
    raw["server_response_ms"] = _audit_numeric(audits, "server-response-time")

    # --- field data (real users, CrUX) — present only for higher-traffic origins
    raw["field_data"] = _parse_field_data(data.get("loadingExperience") or {})

    # --- improvement opportunities (sorted by estimated time savings) ---
    raw["opportunities"] = _parse_opportunities(audits)

    raw["overall_good"] = bool(
        (raw["performance_score"] or 0) >= 90
        and raw["lcp_good"]
        and raw["cls_good"]
    )
    return raw


def _parse_field_data(loading: dict[str, Any]) -> dict[str, Any]:
    metrics = loading.get("metrics") or {}
    if not metrics:
        return {"available": False}

    def _metric(key: str) -> tuple[int | None, str | None]:
        m = metrics.get(key) or {}
        pct = m.get("percentile")
        return (int(pct) if isinstance(pct, (int, float)) else None, m.get("category"))

    lcp_p, lcp_cat = _metric("LARGEST_CONTENTFUL_PAINT_MS")
    cls_p, cls_cat = _metric("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    inp_p, inp_cat = _metric("INTERACTION_TO_NEXT_PAINT")
    fcp_p, fcp_cat = _metric("FIRST_CONTENTFUL_PAINT_MS")

    # CrUX reports CLS percentile ×100 (e.g. 10 → 0.10). Normalize for display.
    cls_value = round(cls_p / 100, 2) if cls_p is not None else None

    return {
        "available": True,
        "overall": loading.get("overall_category"),
        "lcp_ms": lcp_p,
        "lcp_category": lcp_cat,
        "cls": cls_value,
        "cls_category": cls_cat,
        "inp_ms": inp_p,
        "inp_category": inp_cat,
        "fcp_ms": fcp_p,
        "fcp_category": fcp_cat,
    }


def _parse_opportunities(audits: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for audit_id, audit in audits.items():
        if not isinstance(audit, dict):
            continue
        details = audit.get("details") or {}
        if details.get("type") != "opportunity":
            continue
        savings = details.get("overallSavingsMs")
        if not isinstance(savings, (int, float)) or savings < 150:
            # Sub-150ms savings aren't worth a recommendation card.
            continue
        out.append(
            {
                "id": audit_id,
                "title": audit.get("title"),
                "savings_ms": int(savings),
            }
        )
    out.sort(key=lambda o: o["savings_ms"], reverse=True)
    return out


def _audit_numeric(audits: dict[str, Any], audit_id: str) -> float | None:
    audit = audits.get(audit_id) or {}
    value = audit.get("numericValue")
    return float(value) if isinstance(value, (int, float)) else None


def _audit_display(audits: dict[str, Any], audit_id: str) -> str | None:
    audit = audits.get(audit_id) or {}
    disp = audit.get("displayValue")
    return str(disp) if disp else None


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str((body.get("error") or {}).get("message") or body)[:200]
    except ValueError:
        return resp.text[:200]


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _emit(progress: ProgressCb, step: str, detail: dict | None = None) -> None:
    if progress is None:
        return
    try:
        progress(step, detail)
    except Exception:  # narration must never break the audit
        logger.debug("pagespeed progress callback raised", exc_info=True)


# --- scoring helpers used by recommendations ---------------------------------


def _grade_phrase(score: int) -> str:
    if score >= 90:
        return "fast"
    if score >= 50:
        return "okay, with room to improve"
    return "slow"


# Curated, coach-voice copy for the most common Lighthouse opportunities.
# Anything not in here falls back to a generic (but still friendly) card so we
# never surface raw Lighthouse jargon to a non-technical owner.
_OPPORTUNITY_COPY: dict[str, dict[str, str]] = {
    "render-blocking-resources": {
        "title": "Stop scripts and styles from blocking your first paint",
        "how": (
            "Some CSS/JavaScript files load before anything appears on screen, "
            "so visitors stare at a blank page longer than they need to.\n\n"
            "1. In your site builder's SEO/performance settings, turn on "
            "**defer JavaScript** and **load CSS asynchronously** if available.\n"
            "2. On WordPress, a caching plugin (LiteSpeed, WP Rocket) does this "
            "with one toggle.\n"
            "3. Re-run this audit to confirm the first paint got faster."
        ),
        "time": "30 min",
        "impact": "big",
    },
    "uses-optimized-images": {
        "title": "Compress your images so the page loads faster",
        "how": (
            "Large photos are the #1 cause of a slow local-business site.\n\n"
            "1. Run your images through a free compressor (TinyPNG, Squoosh) "
            "before uploading.\n"
            "2. If your builder supports it, enable automatic image "
            "optimization / lazy-loading.\n"
            "3. Re-run this audit — the savings show up immediately."
        ),
        "time": "20 min",
        "impact": "big",
    },
    "modern-image-formats": {
        "title": "Serve images in a modern format (WebP)",
        "how": (
            "WebP images are 25–35% smaller than JPEG/PNG at the same quality.\n\n"
            "1. Export or convert your photos to **WebP** (Squoosh does this free).\n"
            "2. Most modern site builders have a 'serve next-gen images' toggle.\n"
            "3. Re-run this audit to confirm."
        ),
        "time": "20 min",
        "impact": "medium",
    },
    "uses-responsive-images": {
        "title": "Send phone-sized images to phones",
        "how": (
            "Right now full-desktop images are being downloaded on mobile, "
            "wasting your visitors' data and time.\n\n"
            "1. Enable **responsive images** in your theme/builder settings.\n"
            "2. Re-run this audit to confirm the mobile payload dropped."
        ),
        "time": "15 min",
        "impact": "medium",
    },
    "unused-javascript": {
        "title": "Remove JavaScript your pages don't use",
        "how": (
            "Unused scripts still have to download and parse, slowing the page.\n\n"
            "1. Audit your plugins/embeds and remove anything you no longer use.\n"
            "2. A caching plugin can defer or split the rest.\n"
            "3. Re-run this audit to confirm."
        ),
        "time": "professional help",
        "impact": "medium",
    },
    "unused-css-rules": {
        "title": "Trim unused CSS",
        "how": (
            "Large stylesheets where most rules go unused add load time.\n\n"
            "1. A caching/optimization plugin can strip unused CSS automatically.\n"
            "2. Re-run this audit to confirm."
        ),
        "time": "professional help",
        "impact": "small",
    },
    "uses-text-compression": {
        "title": "Turn on text compression (gzip / brotli)",
        "how": (
            "Compressing HTML/CSS/JS in transit is a free, one-time win.\n\n"
            "1. Most hosts enable gzip/brotli by default — check your hosting "
            "or CDN dashboard for a **compression** toggle.\n"
            "2. On Cloudflare it's on by default; confirm it's not disabled.\n"
            "3. Re-run this audit to confirm."
        ),
        "time": "10 min",
        "impact": "medium",
    },
    "server-response-time": {
        "title": "Speed up your server's first response",
        "how": (
            "Your server takes a while to send the very first byte, which "
            "delays everything else.\n\n"
            "1. Turn on page caching (a plugin or your host's built-in cache).\n"
            "2. Consider a CDN like Cloudflare (free tier) in front of your site.\n"
            "3. If it persists, ask your host about a faster plan — shared "
            "hosting is often the bottleneck."
        ),
        "time": "professional help",
        "impact": "medium",
    },
}


def _recommendations(raw: dict[str, Any]) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []
    score = raw.get("performance_score") or 0

    # --- Core Web Vitals first: the three signals Google ranks on ---
    if raw.get("lcp_ms") is not None and not raw.get("lcp_good"):
        secs = raw["lcp_ms"] / 1000
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Speed up your largest content (LCP)",
                body_markdown=(
                    "**Why it matters**\n\n"
                    f"Your main content takes about **{secs:.1f}s** to appear on "
                    "mobile — Google's target is under 2.5s. Slow loads cost you "
                    "both search ranking and impatient visitors who bounce before "
                    "the page shows up.\n\n"
                    "**How to fix it**\n\n"
                    "1. The usual culprit is a big hero image — compress it "
                    "(TinyPNG / Squoosh) and make sure it isn't lazy-loaded.\n"
                    "2. Turn on page caching so the server responds faster.\n"
                    "3. Re-run this audit to confirm the load time dropped."
                ),
                estimated_impact="big",
                estimated_time="30 min",
                verify_signal="performance.lcp_good",
            )
        )

    if raw.get("cls") is not None and not raw.get("cls_good"):
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Stop your layout from jumping around (CLS)",
                body_markdown=(
                    "**Why it matters**\n\n"
                    f"Your page shifts as it loads (layout-shift score "
                    f"**{raw['cls']:.2f}**, target under 0.10). Content jumping "
                    "while someone is reading or tapping is one of the most "
                    "frustrating things on mobile — and Google measures it.\n\n"
                    "**How to fix it**\n\n"
                    "1. Set explicit **width and height** on images and embeds so "
                    "the browser reserves their space before they load.\n"
                    "2. Avoid inserting banners/ads above content that's already "
                    "visible.\n"
                    "3. Re-run this audit to confirm the shifting settled down."
                ),
                estimated_impact="medium",
                estimated_time="professional help",
                verify_signal="performance.cls_good",
            )
        )

    if raw.get("tbt_ms") is not None and not raw.get("tbt_good"):
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Make the page respond to taps faster",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Heavy JavaScript is blocking the page from responding to "
                    "taps and scrolls for the first few seconds. Visitors who "
                    "tap a button and get nothing often assume it's broken.\n\n"
                    "**How to fix it**\n\n"
                    "1. Remove plugins/embeds you don't really need.\n"
                    "2. Turn on **defer JavaScript** in your builder or caching "
                    "plugin.\n"
                    "3. Re-run this audit to confirm responsiveness improved."
                ),
                estimated_impact="medium",
                estimated_time="professional help",
                verify_signal="performance.tbt_good",
            )
        )

    # --- then up to two highest-impact Lighthouse opportunities ---
    remaining = max(0, 4 - len(recs))
    for opp in raw.get("opportunities", [])[:remaining]:
        copy = _OPPORTUNITY_COPY.get(opp["id"])
        saved = opp.get("savings_ms") or 0
        if copy:
            recs.append(
                RecommendationDraft(
                    severity="medium" if saved >= 1000 else "low",
                    title=copy["title"],
                    body_markdown=(
                        "**Why it matters**\n\n"
                        f"Fixing this could shave roughly **{saved/1000:.1f}s** off "
                        "your load time.\n\n"
                        "**How to fix it**\n\n" + copy["how"]
                    ),
                    estimated_impact=copy["impact"],
                    estimated_time=copy["time"],
                )
            )
        elif opp.get("title"):
            # Generic fallback for an opportunity we don't have bespoke copy
            # for — still framed in plain language, no Lighthouse jargon dump.
            recs.append(
                RecommendationDraft(
                    severity="low",
                    title=opp["title"],
                    body_markdown=(
                        "**Why it matters**\n\n"
                        f"PageSpeed estimates this could save about "
                        f"**{saved/1000:.1f}s** of load time.\n\n"
                        "**How to fix it**\n\n"
                        "1. Most site builders and caching plugins have a toggle "
                        "for this — search their performance settings for the "
                        "phrase above.\n"
                        "2. Re-run this audit to confirm the savings landed."
                    ),
                    estimated_impact="small",
                    estimated_time="professional help",
                )
            )

    # All-clear: keep the card from looking empty + reinforce the win.
    if not recs:
        recs.append(
            RecommendationDraft(
                severity="low",
                title=f"Your site is {_grade_phrase(score)} — speed is in good shape",
                body_markdown=(
                    "**Why it matters**\n\n"
                    f"Your mobile speed score is **{score}/100** and your Core Web "
                    "Vitals are within Google's targets. Fast sites rank better and "
                    "keep more visitors — you're doing this right.\n\n"
                    "**How to fix it**\n\n"
                    "1. Nothing to do! Re-run this audit after big visual changes "
                    "(a new homepage, lots of new photos) to make sure speed holds."
                ),
                estimated_impact="small",
                estimated_time="2 min",
                verify_signal="performance.overall_good",
            )
        )

    return recs
