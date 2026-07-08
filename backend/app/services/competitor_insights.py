"""Competitor insights — the "hybrid" layer described in prompt 04_analysis.

Two responsibilities, in strict order:

1. **Deterministic math** decides the actual fact (what's true, by how much,
   between the user and their competitors). This module is the *only* place
   that decides the message — the LLM is downstream of it.

2. **LLM phrasing** turns the structured fact into one calm sentence. It is
   instructed (system prompt) that it is a summarisation/formatting layer
   and must NOT invent business logic. If the call fails, the key is
   missing, or the SDK isn't installed, we fall back to a deterministic
   template so the UI never has to render "insights are broken".

The Hub renders up to two insight cards: the Top Winning Factor (where the
user is ahead by the largest margin) and the Biggest Opportunity (where
they're behind by the largest margin). Both are derived from the same
latest-observation snapshot used elsewhere in the competitor module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Audit,
    AuditSection,
    Business,
    Competitor,
    CompetitorObservation,
    User,
)
from app.models.enums import AuditSectionName, AuditStatus

logger = logging.getLogger(__name__)


InsightKind = Literal["winning", "opportunity", "matched"]
MetricName = Literal["rating", "review_count"]

# A delta smaller than this on the user-facing scale counts as "matched"
# rather than "winning" / "opportunity". Without this gate, a 4.3 user
# rating against a 4.3 competitor average produced the nonsense card
# "Your rating (4.3★) is currently below the 3 competitors … who
# average 4.3★." Pick thresholds at the precision the UI actually
# renders so the copy never disagrees with the visible numbers.
_MATCHED_THRESHOLDS: dict[MetricName, float] = {
    "rating": 0.05,  # ratings render to one decimal place
    "review_count": 1.0,  # review counts render as whole integers
}


@dataclass(frozen=True)
class InsightFact:
    """The deterministic fact a single insight card is built around.

    ``user_value`` and ``competitor_average`` are typed loose (float) so a
    review_count fact (integers) and a rating fact (decimals) can share the
    same shape without losing precision.

    The named-rival fields exist so the sentence can be *specific* — "the
    nearest target is Slash Resto at 240" — instead of restating the average
    the card already shows. All of them are computed here, deterministically;
    the phrasing layer may only repeat them, never extend them.
    ``closest_above`` is the nearest rival strictly above the user (the next
    target); ``closest_below`` the nearest strictly below (the chaser).
    Frozen + hashable on purpose: the LLM sentence cache keys on this.
    """

    kind: InsightKind
    metric: MetricName
    user_value: float
    competitor_average: float
    competitor_sample_size: int
    delta: float  # always reported as (user - competitor_average)
    ahead_of_count: int = 0  # rivals strictly below the user on this metric
    closest_above_name: str | None = None
    closest_above_value: float | None = None
    closest_below_name: str | None = None
    closest_below_value: float | None = None


@dataclass(frozen=True)
class InsightCard:
    fact: InsightFact
    headline: str
    sentence: str


_METRIC_LABELS: dict[MetricName, str] = {
    "rating": "average rating",
    "review_count": "review count",
}


def _user_latest_maps_snapshot(db: Session, business_id: int) -> dict | None:
    """Latest Maps-section snapshot for the user's business, or None.

    Pulls from the same place the trends endpoint does — the Maps section's
    ``raw_data_json`` on the most recent completed audit. Returns None if
    the business has no completed audits yet or the Maps section never ran.
    """
    audit: Audit | None = (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .first()
    )
    if audit is None:
        return None
    section: AuditSection | None = (
        db.query(AuditSection)
        .filter(
            AuditSection.audit_id == audit.id,
            AuditSection.section == AuditSectionName.maps,
        )
        .one_or_none()
    )
    if section is None:
        return None
    raw = section.raw_data_json
    return raw if isinstance(raw, dict) else None


@dataclass(frozen=True)
class RivalSnapshot:
    """Latest observation for one named competitor — name travels with the
    numbers so the insight sentence can point at a real rival, not just an
    anonymous average."""

    name: str
    rating: float | None
    review_count: int | None


def _competitor_latest_snapshots(db: Session, business_id: int) -> list[RivalSnapshot]:
    """One row per active competitor — their most recent observation.

    Mirrors ``_latest_observation_map`` in the competitors API so the hub's
    insight math and the competitor list see the same snapshot.
    """
    competitors: list[Competitor] = (
        db.query(Competitor)
        .filter(
            Competitor.business_id == business_id,
            Competitor.archived_at.is_(None),
        )
        .all()
    )
    if not competitors:
        return []
    names = {c.id: c.name for c in competitors}
    rows: list[CompetitorObservation] = (
        db.query(CompetitorObservation)
        .filter(CompetitorObservation.competitor_id.in_(list(names)))
        .order_by(
            desc(CompetitorObservation.observed_at),
            desc(CompetitorObservation.id),
        )
        .all()
    )
    latest: dict[int, CompetitorObservation] = {}
    for row in rows:
        latest.setdefault(row.competitor_id, row)
    return [
        RivalSnapshot(
            name=names.get(comp_id) or "a competitor",
            rating=obs.rating,
            review_count=obs.review_count,
        )
        for comp_id, obs in latest.items()
    ]


def _facts_for(
    user_snapshot: dict, rivals: list[RivalSnapshot]
) -> list[InsightFact]:
    """Compute one (user, competitor avg, delta) fact per comparable metric.

    Skips a metric entirely when either side has no data — partial facts
    would force the phrasing layer to invent context, which is the one
    thing the prompt explicitly forbids.
    """
    facts: list[InsightFact] = []
    for metric in ("rating", "review_count"):
        user_value = user_snapshot.get(metric)
        if user_value is None:
            continue
        named: list[tuple[str, float]] = []
        for rival in rivals:
            value = rival.rating if metric == "rating" else rival.review_count
            if value is None:
                continue
            named.append((rival.name, float(value)))
        if not named:
            continue
        comp_values = [v for _, v in named]
        avg = sum(comp_values) / len(comp_values)
        user_f = float(user_value)
        delta = user_f - avg
        threshold = _MATCHED_THRESHOLDS[metric]
        if abs(delta) < threshold:
            kind: InsightKind = "matched"
        elif delta > 0:
            kind = "winning"
        else:
            kind = "opportunity"

        # Named-rival context, all deterministic: the nearest rival above
        # (the next target) and below (the closest chaser), at the same
        # precision the UI renders so the copy can't disagree with the card.
        above = [(n, v) for n, v in named if v - user_f >= threshold]
        below = [(n, v) for n, v in named if user_f - v >= threshold]
        closest_above = min(above, key=lambda nv: nv[1]) if above else None
        closest_below = max(below, key=lambda nv: nv[1]) if below else None

        facts.append(
            InsightFact(
                kind=kind,
                metric=metric,  # type: ignore[arg-type]
                user_value=user_f,
                competitor_average=avg,
                competitor_sample_size=len(named),
                delta=delta,
                ahead_of_count=len(below),
                closest_above_name=closest_above[0] if closest_above else None,
                closest_above_value=closest_above[1] if closest_above else None,
                closest_below_name=closest_below[0] if closest_below else None,
                closest_below_value=closest_below[1] if closest_below else None,
            )
        )
    return facts


def _format_value(metric: MetricName, value: float) -> str:
    if metric == "rating":
        return f"{value:.1f}★"
    return f"{int(round(value))}"


def _deterministic_sentence(fact: InsightFact) -> str:
    """Fallback phrasing when the LLM path isn't available.

    Hand-written so it can stand in for the LLM output verbatim — calm,
    one sentence, no superlatives, no claims beyond the underlying math.
    Points at a *named* rival where the data supports one: the card
    already shows the average, so the sentence's job is the specific
    next target (or closest chaser), not a restatement.
    """
    metric_label = _METRIC_LABELS[fact.metric]
    user_str = _format_value(fact.metric, fact.user_value)
    comp_str = _format_value(fact.metric, fact.competitor_average)
    sample = fact.competitor_sample_size
    competitor_word = "competitor" if sample == 1 else "competitors"

    if fact.kind == "winning":
        if fact.ahead_of_count == sample and fact.closest_below_name:
            nearest = _format_value(fact.metric, fact.closest_below_value or 0.0)
            return (
                f"Your {metric_label} ({user_str}) leads all {sample} "
                f"{competitor_word} you're tracking — {fact.closest_below_name} "
                f"is closest at {nearest}."
            )
        if fact.closest_above_name:
            # Above the average, but a rival is still ahead — say so honestly.
            target = _format_value(fact.metric, fact.closest_above_value or 0.0)
            return (
                f"Your {metric_label} ({user_str}) is above the average of the "
                f"{sample} {competitor_word} you track, though "
                f"{fact.closest_above_name} is still ahead at {target}."
            )
        return (
            f"Your {metric_label} ({user_str}) is sitting above the {sample} "
            f"{competitor_word} you're tracking, who average {comp_str}."
        )

    if fact.kind == "matched":
        if sample == 1:
            return (
                f"Your {metric_label} ({user_str}) is right in line with the "
                f"one competitor you're tracking, who's also at {comp_str}."
            )
        return (
            f"Your {metric_label} ({user_str}) is right in line with the "
            f"{sample} competitors you're tracking, who also average "
            f"{comp_str}."
        )

    # Opportunity — frame the nearest rival above as the next target.
    if fact.closest_above_name:
        target = _format_value(fact.metric, fact.closest_above_value or 0.0)
        if fact.ahead_of_count > 0:
            return (
                f"Your {metric_label} ({user_str}) is ahead of "
                f"{fact.ahead_of_count} of the {sample} {competitor_word} you "
                f"track — the next target is {fact.closest_above_name} at {target}."
            )
        return (
            f"Your {metric_label} ({user_str}) trails the {sample} "
            f"{competitor_word} you're tracking — the nearest, "
            f"{fact.closest_above_name}, is at {target}."
        )
    return (
        f"Your {metric_label} ({user_str}) is currently below the {sample} "
        f"{competitor_word} you're tracking, who average {comp_str}."
    )


@lru_cache(maxsize=512)
def _llm_sentence(fact: InsightFact, business_name: str) -> str | None:
    """One-sentence summarisation of ``fact`` via Claude Haiku, or None.

    Returns ``None`` (so the caller can fall back) on any failure path:
    missing key, SDK not installed, network error, model returns empty.
    The system prompt locks the model to *summarisation only* — see the
    prompt's "must NOT invent business logic" rule.

    ``lru_cache``: this used to fire on every hub page-load, twice — pure
    cost and latency for a fact that only changes when an audit or the
    weekly competitor refresh writes new numbers. The fact dataclass is
    frozen/hashable, so identical facts hit the cache until the process
    restarts or the numbers actually move. (Failures also cache until
    restart — acceptable: the deterministic fallback is a full substitute,
    and a restart or fresh fact clears it.)
    """
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    try:
        # Lazy import so the backend boots without the SDK installed —
        # production deploys pull it in via requirements.txt, but dev
        # environments without the package shouldn't crash on startup.
        from anthropic import Anthropic
    except ImportError:
        logger.info("competitor_insights: anthropic SDK not installed; using fallback")
        return None

    system_prompt = (
        "You write one sentence for a calm small-business dashboard card. "
        "You get a structured, pre-verified fact comparing the owner's "
        "business to the local competitors they track. Express the most "
        "useful part of that fact in ONE plain sentence, at most 26 words.\n"
        "Voice: speak directly to the owner as 'you/your', like the rest of "
        "the app. Warm, specific, level-headed.\n"
        "Hard rules:\n"
        "- Use ONLY the numbers and names given. Never invent, round "
        "differently, or extrapolate.\n"
        "- No advice, no causes, no predictions.\n"
        "- No hype words (crushing, dominating, skyrocketing) and no "
        "alarm words (losing, falling behind badly).\n"
        "- Prefer the named rival over the average: the card already "
        "shows the average, so the sentence should add the specific — "
        "who's nearest, and the gap.\n"
        "- If behind, frame the nearest rival above as the next target. "
        "If essentially tied, say you're matching the competition.\n"
        "Reply with the sentence only."
    )

    lines = [
        f"Business (the owner's): {business_name}",
        f"Metric: {_METRIC_LABELS[fact.metric]}",
        f"Your value: {_format_value(fact.metric, fact.user_value)}",
        (
            f"Average of {fact.competitor_sample_size} tracked competitor(s): "
            f"{_format_value(fact.metric, fact.competitor_average)}"
        ),
        (
            f"Rivals you're ahead of on this metric: {fact.ahead_of_count} "
            f"of {fact.competitor_sample_size}"
        ),
    ]
    if fact.closest_above_name is not None and fact.closest_above_value is not None:
        lines.append(
            "Nearest rival above you: "
            f"{fact.closest_above_name} at "
            f"{_format_value(fact.metric, fact.closest_above_value)}"
        )
    if fact.closest_below_name is not None and fact.closest_below_value is not None:
        lines.append(
            "Nearest rival below you: "
            f"{fact.closest_below_name} at "
            f"{_format_value(fact.metric, fact.closest_below_value)}"
        )
    lines.append(f"Verdict (already decided): {fact.kind}")
    user_msg = "\n".join(lines) + "\n\nWrite the sentence."

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.anthropic_insights_model,
            max_tokens=100,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception:
        logger.exception("competitor_insights: LLM call failed; using fallback")
        return None

    parts = getattr(response, "content", None) or []
    for block in parts:
        text = getattr(block, "text", None)
        if text:
            stripped = text.strip()
            if stripped:
                return stripped
    return None


def _headline(fact: InsightFact) -> str:
    metric_label = "rating" if fact.metric == "rating" else "review count"
    if fact.kind == "winning":
        return f"Top winning factor · {metric_label}"
    if fact.kind == "matched":
        return f"Matching the market · {metric_label}"
    return f"Biggest opportunity · {metric_label}"


def build_hub_insights(
    db: Session, user: User, business_id: int
) -> list[InsightCard]:
    """Top winning factor + biggest opportunity for one business.

    Returns at most two cards (one of each kind) — whichever metric has the
    largest absolute delta in each direction. Returns an empty list when
    there isn't enough data on either side to make any honest claim.
    """
    business: Business | None = (
        db.query(Business)
        .filter(
            Business.id == business_id,
            Business.user_id == user.id,
            Business.archived_at.is_(None),
        )
        .one_or_none()
    )
    if business is None:
        return []

    user_snapshot = _user_latest_maps_snapshot(db, business.id)
    if not user_snapshot:
        return []

    rivals = _competitor_latest_snapshots(db, business.id)
    if not rivals:
        return []

    facts = _facts_for(user_snapshot, rivals)
    if not facts:
        return []

    winning = [f for f in facts if f.kind == "winning"]
    opportunity = [f for f in facts if f.kind == "opportunity"]
    matched = [f for f in facts if f.kind == "matched"]

    picked: list[InsightFact] = []
    if winning:
        picked.append(max(winning, key=lambda f: f.delta))
    if opportunity:
        picked.append(min(opportunity, key=lambda f: f.delta))
    # Fall back to a "matched" fact when neither side has anything to
    # surface — otherwise the user sees an empty insights pane even
    # though we have observations from both them and their competitors.
    if not picked and matched:
        picked.append(matched[0])

    cards: list[InsightCard] = []
    for fact in picked:
        sentence = _llm_sentence(fact, business.name) or _deterministic_sentence(fact)
        cards.append(
            InsightCard(
                fact=fact,
                headline=_headline(fact),
                sentence=sentence,
            )
        )
    return cards
