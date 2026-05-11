"""Pure functions for comparing Name / Address / Phone across sources.

The audit pipeline collects per-source contact details (Maps panel, website
JSON-LD / `tel:` link, Instagram bio) and hands them here for normalization
and pair-wise comparison. No DB access, no network I/O — everything in this
module is deterministic and unit-testable on plain dicts.

The structured-first design choice is documented in the prompt:
``claude_prompts/phase_02_production/bug_fixes/02_nap_consistency_real.md``.
"""

from __future__ import annotations

import re
from typing import Any


SOURCES: tuple[str, ...] = ("maps", "website", "instagram")
LEGS: tuple[str, ...] = ("phone", "address", "name")
PAIRS: tuple[tuple[str, str], ...] = (
    ("maps", "website"),
    ("maps", "instagram"),
    ("website", "instagram"),
)


# --- normalization -----------------------------------------------------------


_NON_PHONE_CHARS = re.compile(r"[^\d+]")


def normalize_phone(s: str | None, default_country: str = "IN") -> str | None:
    """Reduce a phone-number string to E.164 (`+919876543210`).

    Rules (intentionally narrow — see prompt §2):
    - Strip whitespace, parens, dashes, dots; keep digits and one leading `+`.
    - If the result starts with `+`, accept when total digit count is 10–15.
    - If the digit string is exactly 10 long and ``default_country == "IN"``,
      prepend ``+91``.
    - If 11 digits starting with `0` and IN default, drop the `0` and prepend
      ``+91`` (handles legacy STD-style entries).
    - Anything else returns ``None``.

    We deliberately avoid the `phonenumbers` library — the rule set is small
    and explicit, and the audit cares about gross consistency, not full E.164
    correctness.
    """
    if not s:
        return None
    cleaned = _NON_PHONE_CHARS.sub("", s.strip())
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if not digits.isdigit():
            return None
        if 10 <= len(digits) <= 15:
            return "+" + digits
        return None

    if not cleaned.isdigit():
        return None

    if default_country == "IN":
        if len(cleaned) == 10:
            return "+91" + cleaned
        if len(cleaned) == 11 and cleaned.startswith("0"):
            return "+91" + cleaned[1:]
    return None


# Tokens we drop wholesale: very short fragments and connective words. Address
# matching is set-wise so noise like "the" / "at" hurts more than it helps.
_NOISE_TOKENS = frozenset({"the", "at"})

# Common Indian / English address abbreviations → canonical form. Keep the map
# small and deterministic — the goal is to make obvious matches match, not to
# parse every possible street.
_ABBREVIATIONS = {
    "rd": "road",
    "st": "street",
    "ave": "avenue",
    "nr": "near",
    "opp": "opposite",
    "bldg": "building",
    "flr": "floor",
}

_TOKEN_PUNCT = re.compile(r"[^\w\s]")
_SPLIT_RE = re.compile(r"[\s,/]+")


def normalize_address(s: str | None) -> list[str] | None:
    """Lowercase, split, strip punctuation, expand abbreviations.

    Returns the cleaned token list (set-wise comparison happens elsewhere).
    Returns ``None`` for null / empty input so callers can distinguish
    "missing" from "empty after normalization".
    """
    if not s:
        return None
    raw = _TOKEN_PUNCT.sub(" ", s.lower())
    tokens: list[str] = []
    for piece in _SPLIT_RE.split(raw):
        piece = piece.strip()
        if not piece:
            continue
        piece = _ABBREVIATIONS.get(piece, piece)
        if len(piece) < 2:
            continue
        if piece in _NOISE_TOKENS:
            continue
        tokens.append(piece)
    return tokens


def normalize_name(s: str | None) -> str | None:
    if not s:
        return None
    out = " ".join(s.strip().casefold().split())
    return out or None


# --- comparison --------------------------------------------------------------


def _phone_pair(a: str | None, b: str | None) -> str:
    if a is None or b is None:
        return "n/a"
    return "match" if a == b else "mismatch"


def _address_pair(a: list[str] | None, b: list[str] | None) -> str:
    if a is None or b is None:
        return "n/a"
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return "n/a"
    # Token overlap proportional to the smaller set; >= 0.7 reads as "same
    # address with cosmetic differences", below that we flag a mismatch.
    overlap = len(set_a & set_b) / max(min(len(set_a), len(set_b)), 1)
    return "match" if overlap >= 0.7 else "mismatch"


def _name_pair(a: str | None, b: str | None) -> str:
    if a is None or b is None:
        return "n/a"
    return "match" if a == b else "mismatch"


def _all_present_match(pair_states: dict[str, str]) -> bool:
    decided = [v for v in pair_states.values() if v != "n/a"]
    return bool(decided) and all(v == "match" for v in decided)


def _instagram_address_blocked(pair: tuple[str, str]) -> bool:
    return "instagram" in pair


def compare_nap(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare phone / address / name across the three sources.

    ``sources`` shape: ``{"maps": {"name": …, "phone": …, "address": …}, …}``.
    Any source may be missing entirely; any field may be null. Output shape is
    documented in the prompt and consumed by ``scrapers/nap.py`` to build the
    section's recommendations and score.
    """
    raw_phone = {src: (sources.get(src) or {}).get("phone") for src in SOURCES}
    raw_address = {src: (sources.get(src) or {}).get("address") for src in SOURCES}
    raw_name = {src: (sources.get(src) or {}).get("name") for src in SOURCES}

    norm_phone = {src: normalize_phone(v) for src, v in raw_phone.items()}
    norm_address_tokens = {src: normalize_address(v) for src, v in raw_address.items()}
    norm_name = {src: normalize_name(v) for src, v in raw_name.items()}

    phone_pairs: dict[str, str] = {}
    address_pairs: dict[str, str] = {}
    name_pairs: dict[str, str] = {}
    for a, b in PAIRS:
        key = f"{a}_{b}"
        phone_pairs[key] = _phone_pair(norm_phone[a], norm_phone[b])
        # IG never reports a postal address — never count it as a mismatch.
        if _instagram_address_blocked((a, b)):
            address_pairs[key] = "n/a"
        else:
            address_pairs[key] = _address_pair(norm_address_tokens[a], norm_address_tokens[b])
        name_pairs[key] = _name_pair(norm_name[a], norm_name[b])

    return {
        "phone": {
            "values": dict(norm_phone),
            "raw_values": dict(raw_phone),
            "pairs": phone_pairs,
            "all_present_match": _all_present_match(phone_pairs),
        },
        "address": {
            # Surface the joined cleaned tokens too — easier for the dashboard
            # to render than a raw token list.
            "values": {
                src: " ".join(tokens) if tokens else None
                for src, tokens in norm_address_tokens.items()
            },
            "raw_values": dict(raw_address),
            "pairs": address_pairs,
            "all_present_match": _all_present_match(address_pairs),
        },
        "name": {
            "values": dict(norm_name),
            "raw_values": dict(raw_name),
            "pairs": name_pairs,
            "all_present_match": _all_present_match(name_pairs),
        },
    }


# --- scoring -----------------------------------------------------------------


# The address leg has only one "real" pair (maps↔website) because IG is always
# n/a. We don't penalize that — it's a structural property, not a mismatch.
_ADDRESS_PAIRS_THAT_COUNT = ("maps_website",)


def score_nap(comparison: dict[str, Any]) -> int:
    """Apply the prompt's scoring rules to a `compare_nap` output.

    Start at 100. Subtract 15 per mismatch pair on each leg. Subtract 10 per
    leg where no source returned a value. Floor at 0.
    """
    score = 100

    for leg in LEGS:
        leg_data = comparison.get(leg) or {}
        pairs = leg_data.get("pairs") or {}
        values = leg_data.get("values") or {}

        if leg == "address":
            pair_iter = ((k, pairs.get(k, "n/a")) for k in _ADDRESS_PAIRS_THAT_COUNT)
        else:
            pair_iter = pairs.items()

        for _key, state in pair_iter:
            if state == "mismatch":
                score -= 15

        # "Couldn't find your <leg> anywhere" — still informative, smaller hit.
        if leg == "address":
            present = any(values.get(src) for src in ("maps", "website"))
        else:
            present = any(values.get(src) for src in SOURCES)
        if not present:
            score -= 10

    return max(0, min(100, round(score)))
