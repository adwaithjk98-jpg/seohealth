"""NAP (Name / Address / Phone) consistency check.

This is a thin wrapper over ``app.services.nap_compare``. It pulls per-source
contact info from the upstream scrapers' raw_data (passed in via
``prior_results``), feeds them into ``compare_nap``, and turns the comparison
output into a ``SectionResult`` with value-specific recommendations.

Note the signature: ``audit_nap`` takes a second argument that the other
scrapers don't. The runner special-cases this — see
``app/services/audit_runner.py``.
"""

from __future__ import annotations

from typing import Any

from app.services.nap_compare import (
    LEGS,
    SOURCES,
    compare_nap,
    score_nap,
)
from scrapers.types import BusinessInput, RecommendationDraft, SectionResult


_SOURCE_LABEL = {"maps": "Google Maps", "website": "your website", "instagram": "Instagram"}
_LEG_LABEL = {"phone": "phone number", "address": "address", "name": "business name"}


async def audit_nap(
    business: BusinessInput, prior_results: dict[str, dict[str, Any]]
) -> SectionResult:
    sources_input: dict[str, dict[str, Any]] = {}
    for src in SOURCES:
        prior = prior_results.get(src) or {}
        sources_input[src] = {
            "phone": prior.get("phone"),
            "address": prior.get("address"),
            # Use the form-supplied business name as the canonical baseline for
            # every source — none of the underlying scrapers reliably surface
            # the merchant's *registered* name today, so we anchor on the input.
            "name": business.name if src == "maps" else prior.get("name") or business.name,
        }

    comparison = compare_nap(sources_input)
    score = score_nap(comparison)

    raw: dict[str, Any] = {
        "sources_checked": [_SOURCE_LABEL[s] for s in SOURCES if prior_results.get(s)],
        "comparison": comparison,
    }

    recommendations = _build_recommendations(comparison)
    return SectionResult(score=score, status="done", raw_data=raw, recommendations=recommendations)


# --- recommendations ---------------------------------------------------------


def _build_recommendations(comparison: dict[str, Any]) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []

    any_finding = False
    for leg in LEGS:
        leg_data = comparison.get(leg) or {}
        recs.extend(_mismatch_recs(leg, leg_data))
        recs.extend(_missing_recs(leg, leg_data))
        if recs:
            any_finding = True

    if not any_finding:
        recs.append(
            RecommendationDraft(
                severity="low",
                title="Your business details line up across the web",
                body_markdown=(
                    "**Why it matters**\n\n"
                    "Your name, phone, and address agree across Google Maps, your website, "
                    "and Instagram. That's exactly the consistency search engines want to "
                    "see — it tells them you're a real, established local business.\n\n"
                    "**How to fix it**\n\n"
                    "1. Nothing to do! Re-run this audit after any website edit so we can "
                    "catch a slip early."
                ),
                estimated_impact="small",
                estimated_time="2 min",
            )
        )

    return recs


def _mismatch_recs(leg: str, leg_data: dict[str, Any]) -> list[RecommendationDraft]:
    pairs = leg_data.get("pairs") or {}
    raw_values = leg_data.get("raw_values") or {}
    out: list[RecommendationDraft] = []
    for pair_key, state in pairs.items():
        if state != "mismatch":
            continue
        a, b = pair_key.split("_", 1)
        a_val = raw_values.get(a) or ""
        b_val = raw_values.get(b) or ""
        out.append(
            RecommendationDraft(
                severity="high" if leg in ("phone", "address") else "medium",
                title=f"Your {_LEG_LABEL[leg]} doesn't match between {_SOURCE_LABEL[a]} and {_SOURCE_LABEL[b]}",
                body_markdown=(
                    "**Why it matters**\n\n"
                    f"{_SOURCE_LABEL[a].capitalize()} shows `{a_val}`, but {_SOURCE_LABEL[b]} "
                    f"shows `{b_val}`. Search engines compare these signals across the web; "
                    "a small-but-consistent name/spelling mismatch makes you look like two "
                    "different businesses, which weakens your local ranking.\n\n"
                    "**How to fix it**\n\n"
                    "1. Pick the canonical version (we suggest matching what's on your Google "
                    "Maps listing — that's the source most customers see first).\n"
                    "2. Update the other source to match exactly, character for character.\n"
                    "3. Re-run this audit to confirm."
                ),
                estimated_impact="big" if leg == "phone" else "medium",
                estimated_time="10 min",
            )
        )
    return out


def _missing_recs(leg: str, leg_data: dict[str, Any]) -> list[RecommendationDraft]:
    """For each source we expected to find a value on but didn't, suggest a fix."""
    raw_values = leg_data.get("raw_values") or {}
    out: list[RecommendationDraft] = []

    if leg == "address":
        # IG never reports a postal address — silence on IG isn't actionable.
        candidate_sources = ("maps", "website")
    else:
        candidate_sources = SOURCES

    # Only nag about a missing source when at least one *other* source has it —
    # otherwise we have no reference to call this a "consistency" problem.
    have_any = any(raw_values.get(src) for src in candidate_sources)
    if not have_any:
        return out

    for src in candidate_sources:
        if raw_values.get(src):
            continue
        out.append(
            RecommendationDraft(
                severity="medium",
                title=f"We couldn't find your {_LEG_LABEL[leg]} on {_SOURCE_LABEL[src]}",
                body_markdown=(
                    "**Why it matters**\n\n"
                    f"Your {_LEG_LABEL[leg]} appears on other sources but not on "
                    f"{_SOURCE_LABEL[src]}. Each missing copy is one fewer place customers "
                    "(and search engines) can confirm you're the same business.\n\n"
                    "**How to fix it**\n\n"
                    + _missing_how_to(leg, src)
                ),
                estimated_impact="medium",
                estimated_time="10 min",
            )
        )
    return out


def _missing_how_to(leg: str, source: str) -> str:
    if source == "maps":
        return (
            "1. Open Google Maps → your listing → **Edit profile** → **Contact**.\n"
            f"2. Add the same {_LEG_LABEL[leg]} you use elsewhere.\n"
            "3. Save and confirm in a private browser window."
        )
    if source == "website":
        if leg == "phone":
            return (
                "1. On your contact / footer area, add the phone as a tappable link: "
                "`<a href=\"tel:+91...\">+91 …</a>`.\n"
                "2. Bonus: add it to your `LocalBusiness` JSON-LD if you have one — "
                "search engines pick it up faster.\n"
                "3. Re-run this audit to confirm."
            )
        return (
            "1. Add a `LocalBusiness` schema block to your homepage with the address.\n"
            "2. Or simply put the address in the footer — most parsers find it either way.\n"
            "3. Re-run this audit to confirm."
        )
    if source == "instagram":
        return (
            "1. Open Instagram → your profile → **Edit profile** → **Contact options**.\n"
            f"2. Add the same {_LEG_LABEL[leg]} you use elsewhere.\n"
            "3. Save and re-check from a logged-out browser."
        )
    return "1. Update the source to match.\n2. Re-run this audit to confirm."
