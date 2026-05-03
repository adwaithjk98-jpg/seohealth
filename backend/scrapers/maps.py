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
from typing import Any

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scrapers.driver import chrome_driver, detect_captcha
from scrapers.types import BusinessInput, RecommendationDraft, SectionResult

logger = logging.getLogger(__name__)

PANEL_WAIT_S = 12
RATING_PATTERN = re.compile(r"\b([1-5](?:\.\d)?)\s*(?:stars?)?\s*\(([\d,]+)\)")


async def audit_maps(business: BusinessInput) -> SectionResult:
    """Run the Maps audit for a business in a worker thread."""
    return await asyncio.to_thread(_audit_maps_sync, business)


def _audit_maps_sync(business: BusinessInput) -> SectionResult:
    target_url = business.maps_url or _build_search_url(business.name, business.city)

    with chrome_driver() as driver:
        try:
            driver.get(target_url)
        except TimeoutException as exc:
            raise RuntimeError(f"Maps page load timed out: {exc}") from exc
        except WebDriverException as exc:
            raise RuntimeError(f"Maps page load failed: {exc}") from exc

        try:
            WebDriverWait(driver, PANEL_WAIT_S).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )
        except TimeoutException:
            pass  # let the parser try anyway; it'll mark a partial result

        detect_captcha(driver)
        raw = _extract_panel(driver)

    if not raw.get("found"):
        raw["url"] = target_url
        return SectionResult(
            score=0,
            status="failed",
            raw_data=raw,
            recommendations=[],
        )

    raw["url"] = driver_current_url_safe(target_url, raw)
    score = _score_maps(raw)
    recommendations = _recommendations(raw)
    return SectionResult(score=score, status="done", raw_data=raw, recommendations=recommendations)


def driver_current_url_safe(fallback: str, raw: dict[str, Any]) -> str:
    return raw.get("url") or fallback


# --- extraction --------------------------------------------------------------


def _build_search_url(name: str, city: str) -> str:
    query = urllib.parse.quote_plus(f"{name} {city}")
    return f"https://www.google.com/maps/search/{query}"


def _extract_panel(driver: WebDriver) -> dict[str, Any]:
    """Pull rating / review count / category / hours / website indicator."""
    raw: dict[str, Any] = {"found": False}

    name = _safe_text(driver, By.CSS_SELECTOR, "h1")
    if name:
        raw["name"] = name
        raw["found"] = True

    page_source = ""
    try:
        page_source = driver.page_source
    except WebDriverException:
        pass

    rating, review_count = _parse_rating_and_reviews(driver, page_source)
    if rating is not None:
        raw["rating"] = rating
    if review_count is not None:
        raw["review_count"] = review_count

    category = _parse_category(driver)
    if category:
        raw["category"] = category

    raw["has_hours"] = _has_hours(driver, page_source)
    raw["has_website_link"] = _has_website_link(driver)
    raw["photo_count"] = _estimate_photo_count(page_source)
    # Reply-to-reviews and recent-review counts require deep panel navigation
    # (clicking "Reviews", scrolling, parsing each card). Surface conservative
    # defaults for now so the score still reflects what we *did* observe.
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
    try:
        el = driver.find_element(By.CSS_SELECTOR, "button[aria-label*='reviews']")
        label = el.get_attribute("aria-label") or el.text or ""
        m = re.search(r"([\d,]+)\s+reviews?", label, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))
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


def _has_website_link(driver: WebDriver) -> bool:
    try:
        driver.find_element(By.CSS_SELECTOR, "a[data-item-id='authority']")
        return True
    except WebDriverException:
        pass
    try:
        driver.find_element(By.CSS_SELECTOR, "a[aria-label*='Website']")
        return True
    except WebDriverException:
        return False


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
            )
        )

    return recs
