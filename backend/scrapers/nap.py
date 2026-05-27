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
    # Sources actually audited (Maps / Website / Instagram successes). The
    # runner strips failed sections from ``prior_results`` so a skipped
    # source isn't mistaken for "we checked and it was empty".
    audited_sources = frozenset(prior_results.keys())

    # NAP is a *consistency* check — with fewer than two real sources we have
    # nothing to compare, so reporting any score (least of all 100/100) is
    # dishonest. Mark the section failed so the overall reflects the gap and
    # the per-pillar card prompts the user to fix the underlying data.
    if len(audited_sources) < 2:
        missing = [_SOURCE_LABEL[s] for s in SOURCES if s not in audited_sources]
        return SectionResult(
            score=0,
            status="failed",
            raw_data={
                "sources_checked": [_SOURCE_LABEL[s] for s in SOURCES if s in audited_sources],
                "audited_sources": sorted(audited_sources),
                "skipped_reason": "need_two_sources",
                "missing_sources": missing,
            },
            recommendations=[_no_comparison_rec(missing)],
        )

    sources_input: dict[str, dict[str, Any]] = {}
    for src in SOURCES:
        prior = prior_results.get(src) or {}
        # Only Maps falls back to the form-supplied name (Maps doesn't
        # reliably surface the merchant's *registered* name in the panel,
        # and the form input is the canonical baseline). For website and
        # Instagram we use only what the scraper actually surfaced —
        # falling back here was making the sub-check claim "Website:
        # Proxy Cafe" even when website was never scraped.
        if src == "maps":
            name = business.name
        else:
            name = prior.get("name") if src in audited_sources else None
        sources_input[src] = {
            "phone": prior.get("phone") if src in audited_sources else None,
            "address": prior.get("address") if src in audited_sources else None,
            "name": name,
        }

    comparison = compare_nap(sources_input)
    score = score_nap(comparison)

    raw: dict[str, Any] = {
        "sources_checked": [_SOURCE_LABEL[s] for s in SOURCES if s in audited_sources],
        "audited_sources": sorted(audited_sources),
        "comparison": comparison,
    }

    recommendations = _build_recommendations(comparison, audited_sources)
    return SectionResult(score=score, status="done", raw_data=raw, recommendations=recommendations)


def _no_comparison_rec(missing_sources: list[str]) -> RecommendationDraft:
    """Recommendation shown when NAP couldn't run for lack of sources."""
    missing_str = " and ".join(missing_sources) if missing_sources else "your website and Instagram"
    return RecommendationDraft(
        severity="high",
        title="Add your website and Instagram so we can cross-check your details",
        body_markdown=(
            "**Why it matters**\n\n"
            "NAP consistency is about whether your business name, phone, and address line up "
            "across the places customers (and Google) see you — Google Maps, your website, and "
            f"Instagram. We could only check one source this time ({missing_str} weren't "
            "available), so there's nothing to compare against yet.\n\n"
            "**How to fix it**\n\n"
            "1. Add your website URL on the home page so we can scrape its contact info.\n"
            "2. Add your Instagram handle so we can read your bio's contact options.\n"
            "3. Re-run this audit — once we have at least two sources, we'll compare them and "
            "flag any mismatches."
        ),
        estimated_impact="big",
        estimated_time="10 min",
        fix_target="nap",
    )


# --- recommendations ---------------------------------------------------------


def _build_recommendations(
    comparison: dict[str, Any], audited_sources: frozenset[str]
) -> list[RecommendationDraft]:
    recs: list[RecommendationDraft] = []

    any_finding = False
    for leg in LEGS:
        leg_data = comparison.get(leg) or {}
        recs.extend(_mismatch_recs(leg, leg_data))
        recs.extend(_missing_recs(leg, leg_data, audited_sources))
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
                fix_target="nap",
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
                # Either side could be the one the user edits; route the
                # investigation through the NAP section. Filtering by
                # opt-out happens upstream — NAP only emits comparisons
                # between sources the user *hasn't* opted out of.
                fix_target="nap",
            )
        )
    return out


def _missing_recs(
    leg: str,
    leg_data: dict[str, Any],
    audited_sources: frozenset[str],
) -> list[RecommendationDraft]:
    """For each source we expected to find a value on but didn't, suggest a fix.

    Restricts the candidate set to sources the runner actually scraped — a
    skipped Maps section produces no Maps phone-number, but that's a
    Maps-listing problem (already its own finding), not a "phone missing
    from Maps" one. We only flag a source when we *did* visit it and the
    leg came back empty.
    """
    raw_values = leg_data.get("raw_values") or {}
    out: list[RecommendationDraft] = []

    if leg == "address":
        # IG never reports a postal address — silence on IG isn't actionable.
        base_sources = ("maps", "website")
    else:
        base_sources = SOURCES
    candidate_sources = tuple(s for s in base_sources if s in audited_sources)
    if not candidate_sources:
        return out

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
                # Target the specific source the user would edit — a
                # "missing phone on Instagram" rec disappears for users
                # who've opted out of Instagram via the FTUE answers.
                fix_target=src,
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
