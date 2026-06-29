"""One-line "what changed" headlines for the audit live-feed.

Each scraper persists rich ``raw_data_json`` describing what it found.
The live-feed page shows that data, but a flat dump doesn't read as
news — the user wants the *delta* against last week ("Reviews up 8",
"IG is now linked from your site"). This module turns
``(current_raw, previous_raw)`` into a single short string, or ``None``
when there's nothing newsy to surface.

Kept dependency-free (plain dicts in, string out) so the audit_runner
can call it inline as each section finishes, and so the unit tests
don't need a DB fixture.
"""

from __future__ import annotations

from typing import Any


def section_highlight(
    section: str,
    current: dict[str, Any] | None,
    previous: dict[str, Any] | None,
) -> str | None:
    """Return a one-liner suitable for inline rendering, or ``None``."""
    current = current or {}

    if section == "maps":
        return _maps_highlight(current, previous or {})
    if section == "website":
        return _website_highlight(current, previous or {})
    if section == "instagram":
        return _instagram_highlight(current, previous or {})
    if section == "nap":
        return _nap_highlight(current, previous or {})
    if section == "performance":
        return _performance_highlight(current, previous or {})
    return None


def _maps_highlight(curr: dict[str, Any], prev: dict[str, Any]) -> str | None:
    # Prefer review-count delta — most newsworthy signal on a Maps card.
    curr_reviews = curr.get("review_count")
    prev_reviews = prev.get("review_count")
    if isinstance(curr_reviews, int) and isinstance(prev_reviews, int):
        diff = curr_reviews - prev_reviews
        if diff > 0:
            return f"{diff} new review{'s' if diff != 1 else ''} since last check"
        if diff < 0:
            return f"Down {abs(diff)} review{'s' if diff != -1 else ''} since last check"
    # No previous to diff — fall back to absolute totals so first-audit
    # users still get a vivid line.
    if isinstance(curr_reviews, int):
        rating = curr.get("rating")
        if rating is not None:
            return f"{rating}★ from {curr_reviews:,} reviews"
        return f"{curr_reviews:,} reviews on Google"
    return None


def _website_highlight(curr: dict[str, Any], prev: dict[str, Any]) -> str | None:
    # IG-on-site cross-check is the freshest sub-signal — surface it
    # when it changed state since last time, otherwise on first audit.
    curr_ig = curr.get("ig_link_state")
    prev_ig = prev.get("ig_link_state")
    if curr_ig == "linked" and prev_ig in (None, "missing", "mismatch"):
        return "Instagram is now linked from your site"
    if curr_ig == "missing" and prev_ig == "linked":
        return "Instagram link disappeared from your site"
    if curr_ig == "mismatch":
        actual = curr.get("ig_link_actual")
        return (
            f"Your site links to @{actual} — different from your stated handle"
            if actual
            else "Your site links to a different Instagram account"
        )
    # First-audit fallback — surface the most informative single fact.
    if not curr.get("loaded"):
        return None
    if curr.get("has_meta_description"):
        return "Meta description, OG image — the basics are set"
    return None


def _instagram_highlight(curr: dict[str, Any], prev: dict[str, Any]) -> str | None:
    if curr.get("available") is False:
        return curr.get("note")
    curr_followers = curr.get("followers")
    prev_followers = prev.get("followers")
    if isinstance(curr_followers, int) and isinstance(prev_followers, int):
        diff = curr_followers - prev_followers
        if diff > 0:
            return f"+{diff} follower{'s' if diff != 1 else ''} since last check"
        if diff < 0:
            return f"Lost {abs(diff)} follower{'s' if diff != -1 else ''} since last check"
    if isinstance(curr_followers, int):
        handle = curr.get("handle")
        return (
            f"@{handle} · {curr_followers:,} followers"
            if handle
            else f"{curr_followers:,} followers"
        )
    return None


def _performance_highlight(curr: dict[str, Any], prev: dict[str, Any]) -> str | None:
    # Prefer the score delta — most newsworthy on a speed card.
    curr_score = curr.get("performance_score")
    prev_score = prev.get("performance_score")
    if isinstance(curr_score, int) and isinstance(prev_score, int):
        diff = curr_score - prev_score
        if diff >= 2:
            return f"Speed score up {diff} since last check"
        if diff <= -2:
            return f"Speed score down {abs(diff)} since last check"
    # First-audit / steady fallback — surface the most vivid single fact.
    lcp = curr.get("lcp_display")
    if isinstance(curr_score, int):
        if curr_score >= 90:
            return f"Loads fast — {curr_score}/100 on mobile"
        if lcp:
            return f"Loads in {lcp} on mobile"
        return f"{curr_score}/100 on mobile"
    return None


def _nap_highlight(curr: dict[str, Any], prev: dict[str, Any]) -> str | None:
    # NAP is structural — talk about whether things line up, not the
    # underlying numbers. Two interesting states: "now consistent",
    # "now mismatched."
    comparison = curr.get("comparison") or {}
    prev_comparison = prev.get("comparison") or {}

    def _has_mismatch(c: dict[str, Any]) -> bool:
        for leg_data in c.values():
            for state in (leg_data.get("pairs") or {}).values():
                if state == "mismatch":
                    return True
        return False

    curr_mm = _has_mismatch(comparison)
    prev_mm = _has_mismatch(prev_comparison) if prev_comparison else None

    if comparison and not curr_mm and prev_mm is True:
        return "Your details now line up everywhere"
    if comparison and curr_mm and prev_mm is False:
        return "A mismatch appeared since last check"
    if comparison and not curr_mm:
        sources = curr.get("sources_checked") or []
        if sources:
            return f"Consistent across {' and '.join(sources)}"
    if curr.get("skipped_reason") == "need_two_sources":
        return "Add another channel so we can cross-check"
    return None
