"""Derives per-section sub-checks and friendly summaries from raw audit data.

The dashboard's Layer 2 view shows a list of "sub-checks" for each section
(e.g. "Has hours? ✓", "Replies to reviews? ⚠️"). Rather than asking the
frontend to know how to interpret every scraper's `raw_data_json` shape,
this service maps each section's raw data into a uniform list of
``SubCheck`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from app.models.enums import AuditSectionName


SUB_CHECK_STATUS = {"good", "warn", "bad", "info"}


@dataclass
class SubCheck:
    label: str
    status: str  # one of SUB_CHECK_STATUS
    value: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SUB_CHECK_STATUS:
            raise ValueError(f"unknown sub-check status: {self.status!r}")


# Friendly per-section labels and emojis for the dashboard cards.
SECTION_META: dict[str, dict[str, str]] = {
    "maps": {
        "label": "Google Maps",
        "emoji": "📍",
        "tagline": "How customers find you",
    },
    "website": {
        "label": "Website",
        "emoji": "🌐",
        "tagline": "Your digital storefront",
    },
    "instagram": {
        "label": "Instagram",
        "emoji": "📸",
        "tagline": "Your community channel",
    },
    "nap": {
        "label": "NAP consistency",
        "emoji": "📋",
        "tagline": "Your details across the web",
    },
    "competitors": {
        "label": "Competitors",
        "emoji": "🏘️",
        "tagline": "Who you're up against",
    },
}


def section_meta(section: str) -> dict[str, str]:
    return SECTION_META.get(
        section,
        {"label": section, "emoji": "🔎", "tagline": ""},
    )


def grade_from_score(score: int | None) -> str:
    if score is None:
        return "—"
    if score >= 90:
        return "A"
    if score >= 80:
        return "A-"
    if score >= 75:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 65:
        return "B-"
    if score >= 60:
        return "C+"
    if score >= 55:
        return "C"
    if score >= 50:
        return "C-"
    if score >= 40:
        return "D"
    return "F"


def derive_sub_checks(section: str, raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return a list of dict-form sub-checks for a section's raw_data."""
    if not raw:
        return []

    if section == AuditSectionName.maps.value:
        checks = _maps_checks(raw)
    elif section == AuditSectionName.website.value:
        checks = _website_checks(raw)
    elif section == AuditSectionName.instagram.value:
        checks = _instagram_checks(raw)
    elif section == AuditSectionName.nap.value:
        checks = _nap_checks(raw)
    else:
        checks = []
    return [asdict(c) for c in checks]


def section_summary(section: str, raw: dict[str, Any] | None) -> str | None:
    """One-line plain-English summary for the dashboard card."""
    if not raw:
        return None
    if section == AuditSectionName.maps.value:
        rating = raw.get("rating")
        reviews = raw.get("review_count")
        if rating is not None and reviews is not None:
            return f"{rating} ★ from {reviews:,} reviews"
        return None
    if section == AuditSectionName.website.value:
        url = raw.get("url")
        if url:
            return _hostname(url)
        return None
    if section == AuditSectionName.instagram.value:
        handle = raw.get("handle")
        followers = raw.get("followers")
        if handle and followers is not None:
            return f"@{handle} · {followers:,} followers"
        if handle:
            return f"@{handle}"
        return None
    if section == AuditSectionName.nap.value:
        sources = raw.get("sources_checked") or []
        if sources:
            return f"Checked across {len(sources)} sources"
        return None
    return None


# --- per-section derivations -------------------------------------------------


def _maps_checks(raw: dict[str, Any]) -> list[SubCheck]:
    checks: list[SubCheck] = []

    rating = raw.get("rating")
    review_count = raw.get("review_count")
    if rating is not None and review_count is not None:
        if rating >= 4.5 and review_count >= 100:
            status = "good"
        elif rating >= 4.0:
            status = "good"
        elif rating >= 3.5:
            status = "warn"
        else:
            status = "bad"
        checks.append(
            SubCheck(
                label="Reviews & rating",
                status=status,
                value=f"{rating} ★ ({review_count:,} reviews)",
            )
        )

    photo_count = raw.get("photo_count")
    if photo_count is not None:
        if photo_count >= 30:
            status = "good"
        elif photo_count >= 10:
            status = "warn"
        else:
            status = "bad"
        checks.append(
            SubCheck(
                label="Photos on listing",
                status=status,
                value=f"{photo_count} photos",
            )
        )

    if "has_hours" in raw:
        ok = bool(raw["has_hours"])
        checks.append(
            SubCheck(
                label="Opening hours",
                status="good" if ok else "bad",
                value="Filled in" if ok else "Missing",
            )
        )

    if "has_website_link" in raw:
        ok = bool(raw["has_website_link"])
        checks.append(
            SubCheck(
                label="Website linked",
                status="good" if ok else "bad",
                value="Linked" if ok else "Not linked",
            )
        )

    if "responds_to_reviews" in raw:
        ok = bool(raw["responds_to_reviews"])
        checks.append(
            SubCheck(
                label="Owner replies to reviews",
                status="good" if ok else "warn",
                value="Replying" if ok else "Not yet",
            )
        )

    if "category" in raw and raw["category"]:
        checks.append(
            SubCheck(label="Business category", status="good", value=str(raw["category"]))
        )

    return checks


def _website_checks(raw: dict[str, Any]) -> list[SubCheck]:
    checks: list[SubCheck] = []

    if "loaded" in raw:
        ok = bool(raw["loaded"])
        checks.append(
            SubCheck(
                label="Site loads",
                status="good" if ok else "bad",
                value="Online" if ok else "Couldn't load",
            )
        )

    if "https" in raw:
        ok = bool(raw["https"])
        checks.append(
            SubCheck(
                label="Secure (HTTPS)",
                status="good" if ok else "bad",
                value="Secure" if ok else "Not secure",
            )
        )

    if "has_title" in raw:
        ok = bool(raw["has_title"])
        checks.append(
            SubCheck(
                label="Page title",
                status="good" if ok else "bad",
                value="Set" if ok else "Missing",
            )
        )

    if "has_meta_description" in raw:
        ok = bool(raw["has_meta_description"])
        checks.append(
            SubCheck(
                label="Meta description",
                status="good" if ok else "bad",
                value="Set" if ok else "Missing — Google's making one up",
            )
        )

    if "has_og_image" in raw:
        ok = bool(raw["has_og_image"])
        checks.append(
            SubCheck(
                label="Link-preview image",
                status="good" if ok else "warn",
                value="Set" if ok else "Missing — links look bare",
            )
        )

    if "has_jsonld_localbusiness" in raw:
        ok = bool(raw["has_jsonld_localbusiness"])
        checks.append(
            SubCheck(
                label="LocalBusiness schema",
                status="good" if ok else "warn",
                value="Set" if ok else "Not set up yet",
            )
        )

    if "mobile_viewport" in raw:
        ok = bool(raw["mobile_viewport"])
        checks.append(
            SubCheck(
                label="Mobile-friendly",
                status="good" if ok else "bad",
                value="Yes" if ok else "Missing viewport tag",
            )
        )

    return checks


def _instagram_checks(raw: dict[str, Any]) -> list[SubCheck]:
    checks: list[SubCheck] = []

    handle = raw.get("handle")
    if handle:
        checks.append(SubCheck(label="Handle", status="good", value=f"@{handle}"))

    followers = raw.get("followers")
    if followers is not None:
        if followers >= 1000:
            status = "good"
        elif followers >= 250:
            status = "warn"
        else:
            status = "info"
        checks.append(
            SubCheck(
                label="Followers", status=status, value=f"{followers:,}"
            )
        )

    post_count = raw.get("post_count")
    if post_count is not None:
        if post_count >= 12:
            status = "good"
        elif post_count >= 5:
            status = "warn"
        else:
            status = "bad"
        checks.append(SubCheck(label="Total posts", status=status, value=str(post_count)))

    if "bio_has_website_link" in raw:
        ok = bool(raw["bio_has_website_link"])
        checks.append(
            SubCheck(
                label="Website link in bio",
                status="good" if ok else "bad",
                value="Linked" if ok else "Missing",
            )
        )

    if "bio_has_location" in raw:
        ok = bool(raw["bio_has_location"])
        checks.append(
            SubCheck(
                label="Location in bio",
                status="good" if ok else "warn",
                value="Set" if ok else "Missing",
            )
        )

    last_post = raw.get("last_post_days_ago")
    if last_post is not None:
        if last_post <= 7:
            status = "good"
            value = f"{last_post} days ago"
        elif last_post <= 30:
            status = "warn"
            value = f"{last_post} days ago"
        else:
            status = "bad"
            value = f"{last_post} days ago"
        checks.append(SubCheck(label="Most recent post", status=status, value=value))

    return checks


def _nap_checks(raw: dict[str, Any]) -> list[SubCheck]:
    checks: list[SubCheck] = []

    if "name_consistent" in raw:
        ok = bool(raw["name_consistent"])
        checks.append(
            SubCheck(
                label="Business name matches everywhere",
                status="good" if ok else "warn",
                value="Consistent" if ok else "Mismatched",
            )
        )

    if "phone_consistent" in raw:
        ok = bool(raw["phone_consistent"])
        detail = None
        if not ok:
            parts = []
            if raw.get("maps_phone"):
                parts.append(f"Maps: {raw['maps_phone']}")
            if raw.get("website_phone"):
                parts.append(f"Website: {raw['website_phone']}")
            detail = " · ".join(parts) if parts else None
        checks.append(
            SubCheck(
                label="Phone matches everywhere",
                status="good" if ok else "bad",
                value="Consistent" if ok else "Mismatched",
                detail=detail,
            )
        )

    if "address_consistent" in raw:
        ok = bool(raw["address_consistent"])
        detail = None
        if not ok:
            parts = []
            if raw.get("maps_address"):
                parts.append(f"Maps: {raw['maps_address']}")
            if raw.get("website_address"):
                parts.append(f"Website: {raw['website_address']}")
            detail = " · ".join(parts) if parts else None
        checks.append(
            SubCheck(
                label="Address matches everywhere",
                status="good" if ok else "bad",
                value="Consistent" if ok else "Mismatched",
                detail=detail,
            )
        )

    return checks


def _hostname(url: str) -> str:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or url
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return url
