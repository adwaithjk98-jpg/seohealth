"""Map ``verify_signal`` keys to predicates over a section's raw_data.

This is the load-bearing piece of the fix-loop: when a previous audit
flagged ``website.has_meta_description`` and the user marked it done,
the next audit's website raw_data tells us whether the fix actually
landed. The verifier sits between those two — given a signal key + the
fresh raw_data block, it returns a tri-state:

* ``"verified"``    — signal is positive, the fix is on the site.
* ``"unverified"``  — signal is still negative, the fix didn't land
                       (or hasn't propagated yet).
* ``"unknown"``     — we couldn't check (raw_data missing, e.g.
                       because the user opted out of that pillar or the
                       data has been pruned past the retention window).

The map is intentionally narrow — only recs whose underlying signal is
deterministic and cheap to re-check end up here. NAP cross-source
findings and "professional help" recs stay outside the loop; users
mark those done/dismissed manually.
"""

from __future__ import annotations

from typing import Any, Callable


_Predicate = Callable[[dict[str, Any]], bool | None]


def _has(key: str) -> _Predicate:
    """Truthy-check on a single ``raw[key]``. Returns None if missing
    so the caller can render "unknown" rather than a false negative."""

    def _check(raw: dict[str, Any]) -> bool | None:
        if key not in raw:
            return None
        return bool(raw.get(key))

    return _check


def _ig_link_state_is(target: str) -> _Predicate:
    """IG-on-website cross-check completes when the state matches."""

    def _check(raw: dict[str, Any]) -> bool | None:
        state = raw.get("ig_link_state")
        if state is None or state == "no_input":
            return None
        return state == target

    return _check


def _maps_reply_rate_at_least(threshold: float) -> _Predicate:
    def _check(raw: dict[str, Any]) -> bool | None:
        rate = raw.get("owner_reply_rate")
        if rate is None:
            return None
        try:
            return float(rate) >= threshold
        except (TypeError, ValueError):
            return None

    return _check


# {signal_key: (section_name, predicate)} — section is informational
# (lets the verifier route to the right raw_data block by name).
SIGNAL_MAP: dict[str, tuple[str, _Predicate]] = {
    # Website pillar
    "website.https": ("website", _has("https")),
    "website.has_title": ("website", _has("has_title")),
    "website.has_meta_description": ("website", _has("has_meta_description")),
    "website.has_og_image": ("website", _has("has_og_image")),
    "website.has_jsonld_localbusiness": ("website", _has("has_jsonld_localbusiness")),
    "website.mobile_viewport": ("website", _has("mobile_viewport")),
    "website.ig_linked": ("website", _ig_link_state_is("linked")),
    # Maps pillar
    "maps.replies_to_reviews": ("maps", _maps_reply_rate_at_least(0.1)),
    # Instagram pillar
    "instagram.has_bio_link": ("instagram", _has("has_bio_link")),
    # Performance pillar — the scraper persists boolean *_good flags whenever
    # it has a measurement, so a plain truthy check confirms the fix landed.
    "performance.lcp_good": ("performance", _has("lcp_good")),
    "performance.cls_good": ("performance", _has("cls_good")),
    "performance.tbt_good": ("performance", _has("tbt_good")),
    "performance.overall_good": ("performance", _has("overall_good")),
}


def verify(
    signal: str | None,
    section_raw: dict[str, Any] | None,
) -> str:
    """Return ``'verified'`` / ``'unverified'`` / ``'unknown'``."""
    if not signal:
        return "unknown"
    if signal not in SIGNAL_MAP:
        return "unknown"
    _section_for_signal, predicate = SIGNAL_MAP[signal]
    if section_raw is None:
        return "unknown"
    result = predicate(section_raw)
    if result is None:
        return "unknown"
    return "verified" if result else "unverified"
