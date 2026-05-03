import asyncio

from scrapers.types import BusinessInput, RecommendationDraft, SectionResult

MOCK_DELAY_SECONDS = 1.5


async def audit_nap(business: BusinessInput) -> SectionResult:
    """Mock NAP (Name / Address / Phone) consistency check."""
    await asyncio.sleep(MOCK_DELAY_SECONDS)
    raw = {
        "name": business.name,
        "name_consistent": True,
        "maps_phone": "+91 98765 43210",
        "website_phone": "+91 9876 543 210",
        "instagram_phone": None,
        "phone_consistent": False,
        "maps_address": f"123 Beach Road, {business.city}",
        "website_address": "123 Beach Rd, Kozhikode",
        "address_consistent": False,
        "sources_checked": ["Google Maps", "Website", "Instagram"],
    }
    recommendations = [
        RecommendationDraft(
            severity="high",
            title="Match your phone number across Maps, website, and Instagram",
            body_markdown=(
                "**Why it matters**\n\n"
                "Search engines compare your business details across the web. When the phone "
                "number on Google Maps is formatted differently from the one on your website, "
                "they can't tell if it's the same business — and your local ranking takes a "
                "small hit each time it happens.\n\n"
                "**How to fix it**\n\n"
                "1. Pick one canonical format (we suggest the one on your website).\n"
                "2. Open your Google Maps listing → **Edit profile** → **Contact**, paste the same number.\n"
                "3. Open Instagram → **Edit profile** → **Contact options**, save the same number.\n"
                "4. Re-check from a different device — sometimes spaces and country codes "
                "look identical but aren't."
            ),
            estimated_impact="big",
            estimated_time="10 min",
        ),
        RecommendationDraft(
            severity="medium",
            title="Use the exact same address everywhere",
            body_markdown=(
                "**Why it matters**\n\n"
                "Your Maps listing says \"Beach Road\" but your website says \"Beach Rd\" "
                "with a different city spelling. Tiny differences confuse search engines and "
                "weaken the trust signal that you're a real, established local business.\n\n"
                "**How to fix it**\n\n"
                "1. Decide on the official address (street name, abbreviations, city spelling).\n"
                "2. Update the address on your website footer, contact page, and any structured "
                "data block.\n"
                "3. Update the address on Google Maps to match exactly.\n"
                "4. Mention the same address in your Instagram bio or location tag."
            ),
            estimated_impact="medium",
            estimated_time="15 min",
        ),
    ]
    return SectionResult(score=64, status="done", raw_data=raw, recommendations=recommendations)
