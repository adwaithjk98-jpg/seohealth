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
    "performance": {
        "label": "Site speed",
        "emoji": "⚡",
        "tagline": "How fast your site loads",
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
    elif section == AuditSectionName.performance.value:
        checks = _performance_checks(raw)
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
    if section == AuditSectionName.performance.value:
        score = raw.get("performance_score")
        lcp = raw.get("lcp_display")
        if score is not None and lcp:
            return f"{score}/100 · loads in {lcp}"
        if score is not None:
            return f"{score}/100 on mobile"
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

    # IG-on-website cross-check — only render when we have an answer
    # (skip silent ``no_input`` state so the card isn't cluttered).
    ig_state = raw.get("ig_link_state")
    if ig_state in ("linked", "missing", "mismatch"):
        if ig_state == "linked":
            check_status = "good"
            value = "Linked"
        elif ig_state == "mismatch":
            check_status = "bad"
            actual = raw.get("ig_link_actual") or "another account"
            value = f"Wrong handle: @{actual}"
        else:
            check_status = "warn"
            value = "Not linked"
        checks.append(
            SubCheck(
                label="Instagram linked from site",
                status=check_status,
                value=value,
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


_NAP_LEG_LABEL = {
    "name": "Business name matches everywhere",
    "phone": "Phone matches everywhere",
    "address": "Address matches everywhere",
}
_NAP_SOURCE_LABEL = {"maps": "Maps", "website": "Website", "instagram": "Instagram"}


def _nap_checks(raw: dict[str, Any]) -> list[SubCheck]:
    """Render the new compare_nap() output shape into Layer 2 sub-checks."""
    checks: list[SubCheck] = []
    comparison = raw.get("comparison") or {}
    if not comparison:
        return checks

    for leg in ("name", "phone", "address"):
        leg_data = comparison.get(leg) or {}
        pairs = leg_data.get("pairs") or {}
        raw_values = leg_data.get("raw_values") or {}

        decided = [v for v in pairs.values() if v != "n/a"]
        any_mismatch = any(v == "mismatch" for v in decided)

        if not decided:
            status = "info"
            value = "Not enough data to compare"
        elif any_mismatch:
            status = "bad"
            value = "Mismatched"
        else:
            status = "good"
            value = "Consistent"

        # Detail line: show the actual values per source so the user can see
        # what we're comparing without opening the Layer 3 modal.
        detail_parts: list[str] = []
        for src in ("maps", "website", "instagram"):
            v = raw_values.get(src)
            if v:
                detail_parts.append(f"{_NAP_SOURCE_LABEL[src]}: {v}")
        detail = " · ".join(detail_parts) if detail_parts else None

        checks.append(
            SubCheck(
                label=_NAP_LEG_LABEL[leg],
                status=status,
                value=value,
                detail=detail,
            )
        )

    return checks


_FIELD_CATEGORY_STATUS = {"FAST": "good", "AVERAGE": "warn", "SLOW": "bad"}


def _performance_checks(raw: dict[str, Any]) -> list[SubCheck]:
    """Render PageSpeed results into Layer 2 sub-checks: the overall score,
    the three Core Web Vitals (lab), and — when Google has it — real-user
    field data."""
    checks: list[SubCheck] = []

    score = raw.get("performance_score")
    if score is not None:
        if score >= 90:
            status = "good"
        elif score >= 50:
            status = "warn"
        else:
            status = "bad"
        checks.append(
            SubCheck(label="Overall speed score", status=status, value=f"{score}/100")
        )

    if raw.get("lcp_ms") is not None:
        checks.append(
            SubCheck(
                label="Largest content loads (LCP)",
                status="good" if raw.get("lcp_good") else "bad",
                value=raw.get("lcp_display") or f"{raw['lcp_ms']/1000:.1f}s",
                detail="Google's target is under 2.5s",
            )
        )

    if raw.get("cls") is not None:
        checks.append(
            SubCheck(
                label="Visual stability (CLS)",
                status="good" if raw.get("cls_good") else "warn",
                value=raw.get("cls_display") or f"{raw['cls']:.2f}",
                detail="Lower is better — target under 0.10",
            )
        )

    if raw.get("tbt_ms") is not None:
        checks.append(
            SubCheck(
                label="Responsiveness (blocking time)",
                status="good" if raw.get("tbt_good") else "warn",
                value=raw.get("tbt_display") or f"{int(raw['tbt_ms'])} ms",
                detail="How long taps/scrolls are blocked while loading",
            )
        )

    field = raw.get("field_data") or {}
    if field.get("available"):
        overall = field.get("overall")
        if overall:
            checks.append(
                SubCheck(
                    label="Real-visitor experience (last 28 days)",
                    status=_FIELD_CATEGORY_STATUS.get(overall, "info"),
                    value=overall.replace("_", " ").title(),
                    detail="Measured from real Chrome visitors to your site",
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
