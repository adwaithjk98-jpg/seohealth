"""Real Google Maps scraper.

Fetches a business's Maps listing (either by direct URL or by a name+city
search) and pulls rating, review count, category and a few presence signals
(hours, website link). Runs Selenium in a worker thread so it doesn't block
the asyncio loop.

Failure modes:
- Selenium can't start (Chrome not installed, etc.) → raise; runner marks the
  section failed and continues with the rest of the audit.
- CAPTCHA wall → raise ``CaptchaDetected``; same handling as above.
- Listing not found / parse failure → return SectionResult with status="failed"
  so the dashboard can show "we couldn't find this on Maps" without the whole
  audit crashing.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scrapers.driver import chrome_driver, detect_captcha
from scrapers.types import BusinessInput, ProgressCb, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

PANEL_WAIT_S = 12
RATING_PATTERN = re.compile(r"\b([1-5](?:\.\d)?)\s*(?:stars?)?\s*\(([\d,]+)\)")

# H1 values that mean "Google didn't auto-pick a listing for this query" rather
# than "this is the business's actual page". en-US is our forced locale via
# --lang in the Chrome options, so we only need the English strings.
_SEARCH_RESULTS_H1 = frozenset({"results", "search results"})


async def audit_maps(
    business: BusinessInput, *, progress: ProgressCb = None
) -> SectionResult:
    """Run the Maps audit for a business in a worker thread.

    ``progress`` (optional) is a callback the runner injects so the
    scraper can narrate sub-phases (looking_up → found_listing →
    read_reviews) to the live-analysis stream. Old call sites that
    don't supply it just get the old silent behavior.
    """
    return await asyncio.to_thread(_audit_maps_sync, business, progress)


def _emit(progress: ProgressCb, step: str, detail: dict | None = None) -> None:
    if progress is None:
        return
    try:
        progress(step, detail)
    except Exception:
        # Narration is best-effort — never let it tank a real audit.
        logger.debug("maps progress callback failed for step=%s", step, exc_info=True)


def _audit_maps_sync(
    business: BusinessInput, progress: ProgressCb = None
) -> SectionResult:
    target_url = business.maps_url or _build_search_url(business.name, business.city)

    _emit(progress, "looking_up", {"target": "Google Maps"})

    with chrome_driver() as driver:
        try:
            found = _navigate_to_listing_panel(driver, target_url)
        except TimeoutException as exc:
            raise RuntimeError(f"Maps page load timed out: {exc}") from exc
        except WebDriverException as exc:
            raise RuntimeError(f"Maps page load failed: {exc}") from exc

        _wait_for_review_span(driver)
        _emit(progress, "reading_listing")
        raw = _extract_panel(driver) if found else {"found": False}

    if not raw.get("found"):
        raw["url"] = target_url
        _emit(progress, "listing_not_found")
        return SectionResult(
            score=0,
            status="failed",
            raw_data=raw,
            recommendations=[_listing_not_found_rec(business)],
        )

    raw["url"] = driver_current_url_safe(target_url, raw)
    _emit(
        progress,
        "found_listing",
        {
            "name": raw.get("name"),
            "rating": raw.get("rating"),
            "review_count": raw.get("review_count"),
        },
    )

    score = _score_maps(raw)
    recommendations = _recommendations(raw)
    discovered: dict[str, str | None] = {}
    if raw.get("website_url"):
        discovered["website"] = raw["website_url"]
    return SectionResult(
        score=score,
        status="done",
        raw_data=raw,
        recommendations=recommendations,
        discovered_fields=discovered,
    )


def driver_current_url_safe(fallback: str, raw: dict[str, Any]) -> str:
    return raw.get("url") or fallback


# --- extraction --------------------------------------------------------------


def _build_search_url(name: str, city: str) -> str:
    query = urllib.parse.quote_plus(f"{name} {city}")
    return f"https://www.google.com/maps/search/{query}"


# Selectors for the first result tile on /maps/search/<query>. Google has
# multiple A/B layouts in flight at any time, so we try a couple of stable-ish
# patterns and accept whichever lands first. They all eventually navigate to a
# /maps/place/ URL.
_FIRST_RESULT_SELECTORS = (
    "div[role='feed'] a[href*='/maps/place/']",
    "a.hfpxzc",
    "a[href*='/maps/place/']",
)


def _click_first_search_result(driver: WebDriver) -> bool:
    """Walk into the first result on a /maps/search results page. Returns
    True when the click landed on a real listing (h1 is no longer the
    generic 'Results' chrome).
    """
    for selector in _FIRST_RESULT_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
        except WebDriverException:
            continue
        try:
            href = el.get_attribute("href") or ""
        except WebDriverException:
            href = ""
        try:
            if href and "/maps/place/" in href:
                # Direct navigation is steadier than .click() — avoids
                # intercepted-element errors from overlayed map tiles.
                driver.get(href)
            else:
                el.click()
        except WebDriverException:
            continue
        try:
            WebDriverWait(driver, PANEL_WAIT_S).until(
                lambda d: (d.find_element(By.TAG_NAME, "h1").text or "").strip().lower()
                not in _SEARCH_RESULTS_H1
            )
            return True
        except (TimeoutException, WebDriverException):
            continue
    return False


# The ChIJ-prefixed place_id is embedded in Google's long-form Maps URLs
# inside the ``!19s<id>`` segment of the ``data=`` blob. It's the most
# stable cross-listing identity Google exposes, more reliable than the
# slug or the lat/long. We extract it to verify "after a search-by-name,
# did we land on the same listing we originally tracked?".
_PLACE_ID_PATTERN = re.compile(r"!19s(ChIJ[A-Za-z0-9_-]{16,})")


def _extract_place_id(url: str | None) -> str | None:
    if not url:
        return None
    m = _PLACE_ID_PATTERN.search(url)
    return m.group(1) if m else None


def _wait_for_review_span(driver: WebDriver, seconds: float = 3) -> None:
    """Wait for the F7nice review-count span to render. No-op on timeout
    so listings with zero reviews don't block. Extracted so both scrapers
    apply the same warmup before reading review_count."""
    try:
        WebDriverWait(driver, seconds).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.F7nice [aria-label$='reviews'], div.F7nice [aria-label$='review']")
            )
        )
    except TimeoutException:
        pass


def _navigate_to_listing_panel(driver: WebDriver, target_url: str) -> bool:
    """Drive to ``target_url`` and land on a real ``/maps/place/...`` panel.

    Performs the full audit-style resolution sequence the user-audit
    path uses (and which produces working review_count where direct-URL
    navigation alone often fails):

      1. ``driver.get(target_url)`` and wait for an ``<h1>``.
      2. Hop-twice — if Google resolved to ``/maps/place/...``, navigate
         to that resolved URL fresh once more. The same place page,
         when reached via a drill-in from a search-results page, comes
         back with the review-count sibling stripped; the fresh hop
         restores the full F7nice DOM.
      3. If we landed on a ``/maps/search/...`` results page instead
         (because the query was ambiguous), drill into the first
         result and hop-twice that one too.
      4. Re-verify the h1 isn't the generic "Results" chrome.

    Returns True when a real listing panel is loaded, False if the
    resolution chain bottoms out at a search-results page or an error.
    Raises ``CaptchaDetected`` (from ``detect_captcha``) — the caller
    decides whether that's recoverable. Other exceptions are swallowed
    so the caller can decide what to do with a partial / failed load.
    """
    try:
        driver.get(target_url)
    except (TimeoutException, WebDriverException):
        return False

    try:
        WebDriverWait(driver, PANEL_WAIT_S).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
    except TimeoutException:
        pass

    detect_captcha(driver)

    # Hop-twice on the first resolution.
    try:
        try:
            WebDriverWait(driver, 4).until(
                lambda d: "/maps/place/" in d.current_url
            )
        except TimeoutException:
            pass
        here = driver.current_url
        if "/maps/place/" in here and here != target_url:
            driver.get(here)
            try:
                WebDriverWait(driver, PANEL_WAIT_S).until(
                    EC.presence_of_element_located((By.TAG_NAME, "h1"))
                )
            except TimeoutException:
                pass
            detect_captcha(driver)
    except WebDriverException:
        pass

    # If we're still on a /maps/search/ results page, drill into the
    # first result + hop-twice that one too.
    on_search_page = False
    try:
        on_search_page = "/maps/search/" in (driver.current_url or "")
    except WebDriverException:
        pass
    if on_search_page:
        if not _click_first_search_result(driver):
            return False
        try:
            try:
                WebDriverWait(driver, 4).until(
                    lambda d: "/maps/place/" in d.current_url
                )
            except TimeoutException:
                pass
            here = driver.current_url
            if "/maps/place/" in here:
                driver.get(here)
                try:
                    WebDriverWait(driver, PANEL_WAIT_S).until(
                        EC.presence_of_element_located((By.TAG_NAME, "h1"))
                    )
                except TimeoutException:
                    pass
                detect_captcha(driver)
        except WebDriverException:
            pass

    # Final sanity: are we on a real listing?
    name = _safe_text(driver, By.CSS_SELECTOR, "h1")
    if not name or name.strip().lower() in _SEARCH_RESULTS_H1:
        return False
    return True


def _extract_panel(driver: WebDriver) -> dict[str, Any]:
    """Pull rating / review count / category / hours / website indicator.

    Returns ``{"found": False}`` alone when no listing was loaded. Sub-check
    fields like ``has_hours`` were previously read off the search-results
    page (always-true-ish defaults from Google's chrome) and rendered as
    "Opening hours: Filled in" alongside an F grade — a confusing
    contradiction. Only populate sub-checks when we know we're looking at
    a real business panel.
    """
    raw: dict[str, Any] = {"found": False}

    name = _safe_text(driver, By.CSS_SELECTOR, "h1")
    # When a search like /maps/search/<query> returns a list (not an auto-picked
    # listing), Google's h1 is the literal "Results" — capturing that as the
    # business name was scoring fake successes against the search-results page.
    if not name or name.strip().lower() in _SEARCH_RESULTS_H1:
        return raw

    raw["name"] = name
    raw["found"] = True

    # The review-count span inside F7nice renders a tick after the rating
    # span on slow/headless Chrome runs. A short explicit wait here means
    # the JS extractor inside ``extract_listing_fields`` reliably sees
    # both children instead of racing on rating-only and falling back to
    # None.
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.F7nice [aria-label$='reviews'], div.F7nice [aria-label$='review']")
            )
        )
    except TimeoutException:
        # Not all listings have reviews yet — fall through and let the
        # JS extractor return None for those cases.
        pass

    # Single shared extraction. Every Maps-panel field comes from
    # ``extract_listing_fields`` — the same call the competitor refresh
    # uses — so parsing fixes (review_count JS extractor, website URL
    # sanitizer, etc.) automatically apply to both paths.
    fields = extract_listing_fields(driver)
    if fields.rating is not None:
        raw["rating"] = fields.rating
    if fields.review_count is not None:
        raw["review_count"] = fields.review_count
    if fields.category:
        raw["category"] = fields.category
    raw["has_hours"] = fields.has_hours
    raw["has_website_link"] = bool(fields.website_url)
    if fields.website_url:
        raw["website_url"] = fields.website_url
    raw["phone"] = fields.phone
    raw["address"] = fields.address
    raw["photo_count"] = fields.photo_count
    # Reply-to-reviews and recent-review counts require deep panel
    # navigation (clicking "Reviews", scrolling, parsing each card) —
    # the audit-only orchestration that ``extract_listing_fields``
    # deliberately doesn't perform. Surface conservative defaults for
    # now so the score still reflects what we *did* observe.
    raw["responds_to_reviews"] = False
    raw["recent_review_count_30d"] = None

    return raw


def _safe_text(driver: WebDriver, by: str, selector: str) -> str | None:
    try:
        el = driver.find_element(by, selector)
        text = (el.text or "").strip()
        return text or None
    except WebDriverException:
        return None


def _parse_rating_and_reviews(
    driver: WebDriver, page_source: str
) -> tuple[float | None, int | None]:
    # Stable-ish: the rating has aria-label like "4.2 stars".
    try:
        el = driver.find_element(By.CSS_SELECTOR, "[role='img'][aria-label*='stars']")
        label = el.get_attribute("aria-label") or ""
        m = re.search(r"([1-5](?:\.\d)?)\s*stars?", label)
        if m:
            rating = float(m.group(1))
            review_count = _find_review_count(driver, page_source)
            return rating, review_count
    except WebDriverException:
        pass

    # Fallback: regex over the page text for "4.2 (3,416)" patterns.
    if page_source:
        match = RATING_PATTERN.search(page_source)
        if match:
            try:
                return float(match.group(1)), int(match.group(2).replace(",", ""))
            except ValueError:
                pass
    return None, None


def _find_review_count(driver: WebDriver, page_source: str) -> int | None:
    # Google Maps no longer puts the review count on a ``button`` —
    # today's DOM has it on a span inside ``div.F7nice`` carrying
    # ``aria-label="N reviews"`` (e.g. ``<span role="img"
    # aria-label="85 reviews">(85)</span>``). The rating span renders
    # before the review-count sibling, so Selenium's ``find_element``
    # often hit between those two renders in headless Chrome and
    # returned None for every audit.
    #
    # Use a JS extractor that runs inside the page (avoids
    # find_element race timing) and tries the aria-label first, then
    # the F7nice textContent regex, then any aria-label across the
    # whole document as a last-resort.
    try:
        rc_text = driver.execute_script(
            """
            // 1. aria-label on the review-count span inside F7nice
            var ar = document.querySelector(
                "div.F7nice [aria-label$='reviews'], div.F7nice [aria-label$='review']"
            );
            if (ar) {
                var m = ar.getAttribute('aria-label').match(/([\\d,.]+\\s*[KMkm]?)\\s+reviews?/i);
                if (m) return m[1];
            }
            // 2. textContent of F7nice itself (works even when reflow lags)
            var f = document.querySelector('div.F7nice');
            if (f) {
                var m2 = (f.textContent || '').match(/\\(([\\d,.]+\\s*[KMkm]?)\\)/);
                if (m2) return m2[1];
            }
            // 3. anywhere else on the page (occasional A/B variants put
            //    the same aria-label on a wrapper button or link)
            var any = document.querySelector(
                "[aria-label$='reviews'], [aria-label$='review']"
            );
            if (any) {
                var m3 = any.getAttribute('aria-label').match(/([\\d,.]+\\s*[KMkm]?)\\s+reviews?/i);
                if (m3) return m3[1];
            }
            return null;
            """
        )
        if rc_text:
            return _parse_review_count_text(rc_text)
    except WebDriverException:
        pass

    if page_source:
        m = RATING_PATTERN.search(page_source)
        if m:
            try:
                return int(m.group(2).replace(",", ""))
            except ValueError:
                return None
    return None


def _parse_review_count_text(value: str) -> int | None:
    """Parse "1,234" / "1.2K" / "85" into an integer review count."""
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    mult = 1.0
    last = text[-1].lower()
    if last in ("k", "m"):
        mult = 1_000.0 if last == "k" else 1_000_000.0
        text = text[:-1].strip()
    try:
        return int(round(float(text) * mult))
    except ValueError:
        return None


def _parse_category(driver: WebDriver) -> str | None:
    # Maps category appears as a button right under the business name.
    try:
        el = driver.find_element(By.CSS_SELECTOR, "button[jsaction*='category']")
        text = (el.text or "").strip()
        return text or None
    except WebDriverException:
        return None


def _has_hours(driver: WebDriver, page_source: str) -> bool:
    try:
        driver.find_element(By.CSS_SELECTOR, "[aria-label*='Hours']")
        return True
    except WebDriverException:
        pass
    if not page_source:
        return False
    lowered = page_source.lower()
    return any(token in lowered for token in ("opens ", "closes ", "open 24 hours", "closed ⋅"))


# Aggregator domains we never want to treat as the merchant's own website.
# Mirrors the filter referenced in AuditAppPlan §7 (Outflow `_AGGREGATOR_DOMAINS`).
_AGGREGATOR_DOMAINS = frozenset(
    {
        "justdial.com",
        "indiamart.com",
        "sulekha.com",
        "zomato.com",
        "swiggy.com",
        "tripadvisor.com",
        "tripadvisor.in",
        "yelp.com",
        "yellowpages.com",
        "facebook.com",
        "m.facebook.com",
        "instagram.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "wa.me",
        "api.whatsapp.com",
        "g.page",
        "google.com",
        "goo.gl",
        "maps.google.com",
        "maps.app.goo.gl",
        "linktr.ee",
        "beacons.ai",
    }
)


def _extract_website_url(driver: WebDriver) -> str | None:
    """Pull the website href from the Maps panel, sanitized.

    Returns the inner URL (Google redirect wrappers stripped, aggregator
    domains filtered) or None if the panel doesn't expose one we want to use.
    """
    href: str | None = None
    for selector in ("a[data-item-id='authority']", "a[aria-label*='Website']"):
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            href = el.get_attribute("href") or None
            if href:
                break
        except WebDriverException:
            continue
    if not href:
        return None

    inner = _unwrap_google_redirect(href)
    if not inner:
        return None
    if _is_aggregator(inner):
        return None
    return inner


def _unwrap_google_redirect(url: str) -> str | None:
    """`https://www.google.com/url?q=https://merchant.com/&...` → inner URL."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    if host.endswith("google.com") and parsed.path in ("/url", "/aclk"):
        params = urllib.parse.parse_qs(parsed.query)
        for key in ("q", "url"):
            if key in params and params[key]:
                inner = params[key][0]
                if inner.lower().startswith(("http://", "https://")):
                    return inner
        return None
    if not url.lower().startswith(("http://", "https://")):
        return None
    return url


def _extract_phone(driver: WebDriver) -> str | None:
    """Pull the phone number from the panel's Phone button (`Phone: +91 …`)."""
    try:
        el = driver.find_element(By.CSS_SELECTOR, "button[data-item-id^='phone:tel:']")
    except WebDriverException:
        return None
    label = el.get_attribute("aria-label") or el.text or ""
    label = label.strip()
    if not label:
        return None
    # Strip the "Phone:" prefix Maps prepends in aria-label.
    lowered = label.lower()
    if lowered.startswith("phone:"):
        label = label[len("Phone:") :].strip()
    return label or None


def _extract_address(driver: WebDriver) -> str | None:
    """Pull the address from the panel's Address button (aria-label is the full street)."""
    try:
        el = driver.find_element(By.CSS_SELECTOR, "button[data-item-id='address']")
    except WebDriverException:
        return None
    label = el.get_attribute("aria-label") or el.text or ""
    label = label.strip()
    if not label:
        return None
    lowered = label.lower()
    if lowered.startswith("address:"):
        label = label[len("Address:") :].strip()
    return label or None


def _is_aggregator(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).netloc or "").lower()
    except ValueError:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in _AGGREGATOR_DOMAINS


def _estimate_photo_count(page_source: str) -> int | None:
    if not page_source:
        return None
    # The "All" photos button is labeled with the photo count e.g. "87 photos".
    m = re.search(r"([\d,]+)\s+photos?", page_source, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


# --- scoring + recommendations ----------------------------------------------


def _listing_not_found_rec(business: BusinessInput) -> RecommendationDraft:
    """Surfaces the "we couldn't find your Maps listing" case as a finding.
    Without this, the dashboard's section detail rendered an F grade *and* the
    cheery "Nothing flagged here — this pillar is in good shape!" empty state,
    which left the user with no idea what to fix.
    """
    by_url = business.maps_url is not None
    return RecommendationDraft(
        severity="high",
        title="We couldn't find your Google Maps listing",
        body_markdown=(
            "**Why it matters**\n\n"
            "Google Maps is where most local customers find a business. If we "
            "can't pull up your listing from "
            + ("the URL you provided" if by_url else f"a search for **{business.name}** in **{business.city}**")
            + ", search engines probably can't either — that means missed calls, "
            "missed bookings, and a weaker local ranking overall.\n\n"
            "**How to fix it**\n\n"
            "1. Search for your business name in Google Maps from your phone "
            "and confirm a profile actually exists.\n"
            "2. If it does, copy the share link from Maps and paste it on the "
            "**Add business** page here — that gives us a direct route in.\n"
            "3. If it doesn't, claim or create a free **Google Business "
            "Profile** at business.google.com using the same business name "
            "and address you use everywhere else.\n"
            "4. Re-run this audit once the listing is live."
        ),
        estimated_impact="big",
        estimated_time="30 min",
    )


def _score_maps(raw: dict[str, Any]) -> int:
    score = 50
    rating = raw.get("rating")
    review_count = raw.get("review_count") or 0
    if rating is not None:
        if rating >= 4.5:
            score += 20
        elif rating >= 4.0:
            score += 15
        elif rating >= 3.5:
            score += 5
        else:
            score -= 10
    if review_count >= 500:
        score += 15
    elif review_count >= 100:
        score += 10
    elif review_count >= 25:
        score += 5

    if raw.get("has_hours"):
        score += 5
    if raw.get("has_website_link"):
        score += 5

    photo_count = raw.get("photo_count") or 0
    if photo_count >= 30:
        score += 5
    elif photo_count < 10:
        score -= 5

    return max(0, min(100, score))


def _recommendations(raw: dict[str, Any]) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []

    if not raw.get("has_hours"):
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Add your opening hours to Google Maps",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Hours are the single most-checked field on a Maps listing. If they're "
                    "missing, customers assume you might be closed and pick a competitor.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Google Maps → search your business → tap **Edit profile**.\n"
                    "2. Choose **Hours** and fill in each day, including any weekly closures.\n"
                    "3. Add **Special hours** for upcoming holidays so customers see accurate info.\n"
                    "4. Save and re-check from a logged-out browser to confirm they show."
                ),
                estimated_impact="big",
                estimated_time="10 min",
            )
        )

    if not raw.get("has_website_link"):
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Link your website from your Maps listing",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "A linked website is a clear quality signal to Google and to customers. "
                    "It also lets you measure traffic from Maps in your analytics.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Google Maps → your listing → **Edit profile** → **Contact**.\n"
                    "2. Paste your homepage URL into the **Website** field.\n"
                    "3. Save and reload Maps in a private window to confirm it appears."
                ),
                estimated_impact="medium",
                estimated_time="5 min",
            )
        )

    photo_count = raw.get("photo_count") or 0
    if photo_count < 10:
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Add 5 more photos to your listing",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Listings with 30+ recent photos get many more profile views. Customers "
                    "scroll the photos before deciding whether to visit.\n\n"
                    "**How to fix it**\n\n"
                    "1. Take 5 phone photos: storefront, interior, two popular items, the team.\n"
                    "2. Open Google Maps → your listing → **Add photo**.\n"
                    "3. Upload them across a week (not all at once) so they look natural.\n"
                    "4. Re-shoot every season — bright daylight photos perform best."
                ),
                estimated_impact="small",
                estimated_time="15 min",
            )
        )

    rating = raw.get("rating")
    review_count = raw.get("review_count") or 0
    if review_count < 25:
        recs.append(
            RecommendationDraft(
                severity="high",
                title="Ask 10 happy customers for a review this month",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Below 25 reviews you're invisible against established competitors. The "
                    "fastest, cheapest lift you can give your ranking is more recent reviews.\n\n"
                    "**How to fix it**\n\n"
                    "1. From Google Maps → your listing → **Share**, copy your review link.\n"
                    "2. Send it personally to your 10 most loyal customers (WhatsApp / SMS works).\n"
                    "3. Print a small card with a QR code at the till for walk-ins.\n"
                    "4. Aim for 2–3 new reviews a week — steady is better than a sudden burst."
                ),
                estimated_impact="big",
                estimated_time="30 min",
            )
        )
    elif rating is not None and rating < 4.0:
        recs.append(
            RecommendationDraft(
                severity="medium",
                title="Reply to recent negative reviews",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "A polite owner reply softens the impact of a 1- or 2-star review and "
                    "shows future customers that you take feedback seriously.\n\n"
                    "**How to fix it**\n\n"
                    "1. Open Google Maps → your listing → **Reviews**, sort by lowest.\n"
                    "2. For each, thank them, apologise briefly, and offer to make it right offline.\n"
                    "3. Avoid arguing in the reply — it reads worse than the review itself.\n"
                    "4. Address the root cause internally so the next batch of reviews trends up."
                ),
                estimated_impact="medium",
                estimated_time="20 min",
                verify_signal="maps.replies_to_reviews",
            )
        )

    return recs


# --- Shared Maps-listing extraction ----------------------------------------
#
# Before 2026-05-28, ``_audit_maps_sync`` (user-business audit) and
# ``_scrape_one_competitor`` (competitor refresh) were two independent
# Selenium routines that each parsed the same Maps panel into different
# field shapes. They drifted: review_count parsing got a JS-extractor fix
# in the audit path that never made it to the competitor path. Same
# review-count span, same DOM, two different parsers, two different bug
# tails.
#
# ``MapsListing`` + ``extract_listing_fields`` collapse that to one
# canonical extraction. Both top-level scrapers now call
# ``extract_listing_fields(driver)`` for everything the Maps panel can
# tell us. Each scraper keeps its own orchestration (the audit adds
# owner-reply scans, photo counts, sub-checks; the competitor refresh
# just persists the metric subset), but a fix to ``review_count`` lands
# in one place and propagates to both.


@dataclass
class MapsListing:
    """Canonical snapshot of what we can extract from a Google Maps panel.

    Field names are the union the rest of the system reads from. Both
    ``_audit_maps_sync`` and ``_scrape_one_competitor`` populate the same
    keys; downstream code (audit raw_data dict, CompetitorMetrics,
    discovery results from the external subprocess) should match these
    names so a single rename here propagates everywhere.

    ``None`` means "we tried and couldn't extract." Callers that need to
    distinguish "tried" from "didn't try" should not call the extractor
    at all in the second case.
    """

    name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str | None = None
    website_url: str | None = None
    instagram_url: str | None = None
    phone: str | None = None
    address: str | None = None
    has_hours: bool = False
    photo_count: int | None = None


def extract_listing_fields(driver: WebDriver) -> MapsListing:
    """Pull every Maps-panel field we know how to extract from a loaded page.

    Assumes the caller has already navigated the driver to the place
    page, performed any hop-twice resolution, and waited for the h1 to
    render. Doesn't raise on a missing field — each extractor returns
    ``None`` independently so a partial listing still surfaces what we
    *did* read.

    The IG panel probe is best-effort — most Maps listings don't link
    Instagram directly. The richer IG-link discovery happens on the
    website scraper (``scrapers/website.py::_extract_instagram_handle``)
    which has a real signal source.
    """
    page_source = ""
    try:
        page_source = driver.page_source
    except WebDriverException:
        pass

    name = _safe_text(driver, By.CSS_SELECTOR, "h1")
    rating, review_count = _parse_rating_and_reviews(driver, page_source)
    category = _parse_category(driver)
    website_url = _extract_website_url(driver)
    phone = _extract_phone(driver)
    address = _extract_address(driver)
    has_hours = _has_hours(driver, page_source)
    photo_count = _estimate_photo_count(page_source)

    instagram_url: str | None = None
    try:
        for anchor in driver.find_elements(By.CSS_SELECTOR, "a[href*='instagram.com/']"):
            href = (anchor.get_attribute("href") or "").strip()
            if href:
                instagram_url = href
                break
    except WebDriverException:
        pass

    return MapsListing(
        name=name,
        rating=rating,
        review_count=review_count,
        category=category,
        website_url=website_url,
        instagram_url=instagram_url,
        phone=phone,
        address=address,
        has_hours=has_hours,
        photo_count=photo_count,
    )


# --- Competitor metrics (Phase 4) -------------------------------------------


@dataclass
class CompetitorMetrics:
    """Lightweight metric snapshot for one competitor listing.

    Phase 4 originally tracked rating + review_count per audit; 4.6 adds
    Instagram follower + post count slots so the Market matrix and Deep
    Dive can offer them as toggle metrics. Both are optional — the
    fetcher leaves them ``None`` until the scraper is extended to
    actually extract IG data, and the DB persists null cleanly. ``error``
    is populated when the listing failed to load so the caller can
    persist a row with null metrics (still useful as a "we tried" signal)
    without aborting the rest of the batch.
    """

    competitor_id: int
    name: str | None = None
    rating: float | None = None
    review_count: int | None = None
    instagram_followers: int | None = None
    instagram_posts: int | None = None
    # Self-heal hooks for the refresh job: when a competitor was tracked
    # before the discovery scraper started returning website / IG fields
    # (or via the manual-add fast path), its Competitor row has
    # ``instagram_url=None`` and the IG metric scrape silently no-ops
    # forever. The competitor metric scraper now extracts both off the
    # Maps panel and exposes them here so the refresh job can patch the
    # Competitor row when it finds them missing.
    website_url: str | None = None
    instagram_url: str | None = None
    error: str | None = None


@dataclass
class CompetitorScrapeTarget:
    """Per-competitor input to the bulk metric fetcher.

    The fetcher used to take just ``(competitor_id, maps_url)`` — direct
    URL navigation only — and reliably failed to extract ``review_count``
    for ~half of listings, because Google strips the F7nice review-count
    span when you arrive at a place page via the long
    ``/maps/place/.../data=!...!rclk=1`` URLs the discovery scraper
    persists. The user-audit path doesn't hit this because it usually
    arrives via a search query, which Google treats as a fresh user
    interaction and renders the full panel for.

    Adding ``name`` + ``city`` lets the competitor fetcher follow the
    same search-by-name flow. ``maps_url`` stays as the fallback for
    when the search resolves to a different listing (place_id
    mismatch) or when name/city aren't available.
    """

    competitor_id: int
    maps_url: str | None
    name: str | None = None
    city: str | None = None


async def fetch_competitor_metrics(
    competitors: list[CompetitorScrapeTarget],
    *,
    progress: ProgressCb = None,
) -> list[CompetitorMetrics]:
    """Pull rating + review_count + IG panel signals per competitor.

    Opens a single Chrome driver and visits each listing sequentially —
    that's cheaper than re-acquiring the driver semaphore per
    competitor on a small VPS, and matches the per-process concurrency
    cap (one driver at a time).
    """
    return await asyncio.to_thread(_fetch_competitor_metrics_sync, competitors, progress)


def _fetch_competitor_metrics_sync(
    competitors: list[CompetitorScrapeTarget], progress: ProgressCb = None
) -> list[CompetitorMetrics]:
    results: list[CompetitorMetrics] = []
    if not competitors:
        return results

    with chrome_driver() as driver:
        for target in competitors:
            _emit(progress, "competitor_started", {"competitor_id": target.competitor_id})
            metric = _scrape_one_competitor(driver, target)
            results.append(metric)
            _emit(
                progress,
                "competitor_finished",
                {
                    "competitor_id": target.competitor_id,
                    "rating": metric.rating,
                    "review_count": metric.review_count,
                    "error": metric.error,
                },
            )
    return results


def _scrape_one_competitor(
    driver: WebDriver, target: CompetitorScrapeTarget
) -> CompetitorMetrics:
    """Scrape one competitor's Maps listing using the same multi-strategy
    flow the user audit uses.

    Strategy order:
      1. **Search-by-name** when ``name`` + ``city`` are present. This
         is what produces working ``review_count`` for the user audit
         path; Google treats search-driven navigation as a fresh user
         interaction and renders the full F7nice DOM. After landing,
         we extract the place_id from the resolved URL and compare it
         to the place_id embedded in the originally-tracked
         ``maps_url`` — if they disagree, the search resolved to the
         wrong listing (common name collisions like "Cafe Coffee Day")
         and we fall through to strategy 2.
      2. **Direct URL navigation** of the stored ``maps_url`` —
         original behavior. Less reliable for review_count but always
         hits the right listing.

    Returns ``CompetitorMetrics`` with whatever fields we read; missing
    data is ``None``, not an error. ``error`` is set only when the
    scrape couldn't make progress at all (driver failure, CAPTCHA).
    """
    competitor_id = target.competitor_id
    expected_place_id = _extract_place_id(target.maps_url)

    # Strategy 1: search-by-name.
    if target.name and target.city:
        search_url = _build_search_url(target.name, target.city)
        try:
            found = _navigate_to_listing_panel(driver, search_url)
        except Exception as exc:  # CaptchaDetected or other
            # Try the fallback rather than failing the whole row —
            # CAPTCHA on a search query doesn't necessarily mean a
            # direct-URL load will fail too (different fingerprint).
            logger.warning(
                "competitor search-by-name failed for %r: %s; falling back to direct URL",
                target.name, exc,
            )
            found = False

        if found:
            landed_place_id = _extract_place_id(driver.current_url)
            if (
                not expected_place_id
                or not landed_place_id
                or landed_place_id == expected_place_id
            ):
                # Same listing (or no place_id to verify against). Extract.
                _wait_for_review_span(driver)
                fields = extract_listing_fields(driver)
                return CompetitorMetrics(
                    competitor_id=competitor_id,
                    name=fields.name,
                    rating=fields.rating,
                    review_count=fields.review_count,
                    website_url=fields.website_url,
                    instagram_url=fields.instagram_url,
                )
            else:
                logger.info(
                    "competitor search resolved to wrong listing (expected place_id=%s, "
                    "got %s) — falling back to direct URL for competitor_id=%s",
                    expected_place_id, landed_place_id, competitor_id,
                )

    # Strategy 2: direct URL navigation (fallback).
    if not target.maps_url:
        return CompetitorMetrics(
            competitor_id=competitor_id,
            error="no maps_url and search-by-name not available",
        )

    try:
        found = _navigate_to_listing_panel(driver, target.maps_url)
    except Exception as exc:  # CaptchaDetected
        return CompetitorMetrics(competitor_id=competitor_id, error=f"captcha: {exc}")
    if not found:
        return CompetitorMetrics(competitor_id=competitor_id, error="panel did not load")

    _wait_for_review_span(driver)
    fields = extract_listing_fields(driver)
    return CompetitorMetrics(
        competitor_id=competitor_id,
        name=fields.name,
        rating=fields.rating,
        review_count=fields.review_count,
        website_url=fields.website_url,
        instagram_url=fields.instagram_url,
    )
