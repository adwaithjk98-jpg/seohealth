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
from typing import Literal

from sqlalchemy import desc, func
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
    """

    kind: InsightKind
    metric: MetricName
    user_value: float
    competitor_average: float
    competitor_sample_size: int
    delta: float  # always reported as (user - competitor_average)


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


def _competitor_latest_observations(
    db: Session, business_id: int
) -> list[CompetitorObservation]:
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
    comp_ids = [c.id for c in competitors]
    rows: list[CompetitorObservation] = (
        db.query(CompetitorObservation)
        .filter(CompetitorObservation.competitor_id.in_(comp_ids))
        .order_by(
            desc(CompetitorObservation.observed_at),
            desc(CompetitorObservation.id),
        )
        .all()
    )
    latest: dict[int, CompetitorObservation] = {}
    for row in rows:
        latest.setdefault(row.competitor_id, row)
    return list(latest.values())


def _facts_for(
    user_snapshot: dict, competitor_obs: list[CompetitorObservation]
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
        comp_values: list[float] = []
        for obs in competitor_obs:
            value = obs.rating if metric == "rating" else obs.review_count
            if value is None:
                continue
            comp_values.append(float(value))
        if not comp_values:
            continue
        avg = sum(comp_values) / len(comp_values)
        delta = float(user_value) - avg
        threshold = _MATCHED_THRESHOLDS[metric]
        if abs(delta) < threshold:
            kind: InsightKind = "matched"
        elif delta > 0:
            kind = "winning"
        else:
            kind = "opportunity"
        facts.append(
            InsightFact(
                kind=kind,
                metric=metric,  # type: ignore[arg-type]
                user_value=float(user_value),
                competitor_average=avg,
                competitor_sample_size=len(comp_values),
                delta=delta,
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
    """
    metric_label = _METRIC_LABELS[fact.metric]
    user_str = _format_value(fact.metric, fact.user_value)
    comp_str = _format_value(fact.metric, fact.competitor_average)
    sample = fact.competitor_sample_size
    competitor_word = "competitor" if sample == 1 else "competitors"
    if fact.kind == "winning":
        return (
            f"Your {metric_label} ({user_str}) is sitting above the {sample} "
            f"{competitor_word} you're tracking, who average {comp_str}."
        )
    if fact.kind == "matched":
        return (
            f"Your {metric_label} ({user_str}) is right in line with the "
            f"{sample} {competitor_word} you're tracking, who also average "
            f"{comp_str}."
        )
    return (
        f"Your {metric_label} ({user_str}) is currently below the {sample} "
        f"{competitor_word} you're tracking, who average {comp_str}."
    )


def _llm_sentence(fact: InsightFact, business_name: str) -> str | None:
    """One-sentence summarisation of ``fact`` via Claude Haiku, or None.

    Returns ``None`` (so the caller can fall back) on any failure path:
    missing key, SDK not installed, network error, model returns empty.
    The system prompt locks the model to *summarisation only* — see the
    prompt's "must NOT invent business logic" rule.
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
        "You are a phrasing layer for a small business analytics dashboard. "
        "You receive a structured fact comparing one business's metric to "
        "the average of its tracked competitors. Your only job is to "
        "express that fact in one calm, plain sentence — at most 25 words. "
        "Rules: do NOT invent any numbers or context not in the fact. Do "
        "NOT speculate about causes. Do NOT recommend actions. Do NOT use "
        "superlatives like 'crushing it' or 'dominating'. Reference the "
        "business by name. If the user is ahead, frame it neutrally; if "
        "behind, frame it as room to grow rather than a problem; if the "
        "deltas are essentially zero, say the user is matching the "
        "competition."
    )

    if fact.kind == "winning":
        direction = "ahead of"
    elif fact.kind == "matched":
        direction = "tracking right alongside"
    else:
        direction = "behind"
    user_msg = (
        f"Business name: {business_name}\n"
        f"Metric: {_METRIC_LABELS[fact.metric]}\n"
        f"{business_name}'s value: {_format_value(fact.metric, fact.user_value)}\n"
        f"Average across {fact.competitor_sample_size} tracked competitor(s): "
        f"{_format_value(fact.metric, fact.competitor_average)}\n"
        f"Direction: {business_name} is {direction} the competitor average "
        f"by {abs(fact.delta):.2f}.\n\n"
        "Write one sentence summarising this fact."
    )

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.anthropic_insights_model,
            max_tokens=120,
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

    competitor_obs = _competitor_latest_observations(db, business.id)
    if not competitor_obs:
        return []

    facts = _facts_for(user_snapshot, competitor_obs)
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
