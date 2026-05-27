"""Compute which pillars are "enabled" for a given business, given the
user's FTUE questionnaire answers (``has_website`` / ``has_instagram``).

Used by the audit-detail read path to (a) drop opted-out pillars from
the overall-score average and the pillar grid, and (b) filter
recommendations whose ``fix_target`` lands on a disabled pillar.

Rules:
* ``maps`` is always enabled — it's the spine of the audit and can't be
  opted out of (users with no Google Maps presence have nothing to
  audit at all).
* ``website`` is enabled unless ``business.has_website is False``.
* ``instagram`` is enabled unless ``business.has_instagram is False``.
  ``None`` means "we never asked yet" — treat as enabled so legacy
  rows behave like they did before the questionnaire shipped.
* ``nap`` is enabled iff at least one of {website, instagram} is
  enabled — otherwise there's no second source to cross-check Maps
  against, and surfacing a NAP pillar with nothing to compare just
  produces an honest-but-empty 0/100.
"""

from __future__ import annotations

from app.models import Business


# Section names are strings (the enum values) so this module doesn't have
# to import the enum and keeps the helper trivially testable on plain
# string sets.
ALWAYS_ON: frozenset[str] = frozenset({"maps"})


def enabled_pillars(business: Business) -> frozenset[str]:
    """Return the set of section names the business has opted in to."""
    enabled: set[str] = set(ALWAYS_ON)

    if business.has_website is not False:
        enabled.add("website")
    if business.has_instagram is not False:
        enabled.add("instagram")

    # NAP is meaningful only with ≥2 sources to compare. Maps is always
    # on, so NAP is enabled iff at least one of {website, instagram} is
    # also enabled.
    if "website" in enabled or "instagram" in enabled:
        enabled.add("nap")

    return frozenset(enabled)


def is_pillar_enabled(business: Business, section: str) -> bool:
    return section in enabled_pillars(business)
