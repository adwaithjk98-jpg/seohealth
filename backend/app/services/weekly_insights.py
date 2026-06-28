"""Weekly Insights — the scroll-narrative "report" engine.

This replaces the old delta-report recap. The product principle (see the
2026-06 design): stop answering *"what changed since the last audit?"* (a flat,
often-empty signal for a local business) and instead answer *"where do you
stand, where are you heading, and how do you compare?"* — which is always
non-empty and always means something.

Everything here is **deterministic with real values** — slopes, ranks, counts,
deltas computed from data we already store (audit history, Maps review counts,
competitor observations, shipped fixes). No scraping, no LLM. Phrasing is warm
templated copy; an LLM polish layer is a deliberate *later* upgrade.

The output is a sequence of "beats" the frontend renders as a vertical scroll:
cover → lead (self-trajectory, the peak) → trajectory → growth → standing
(competitors) → effort → lever → pride. Free users get the cover, lead, pride,
their own trajectory chart (the weekly return hook), and a locked
table-of-contents (the honest taste); paid users get every beat.

Negative beats are framed kindly and forward-looking by design (the brand's
no-doom principle): a dip becomes "here's the one move to bounce back."
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import Audit, Business, Competitor, CompetitorObservation, User
from app.models.enums import AuditSectionName, AuditStatus, UserPlan
from app.services.audit_view import build_audit_detail

_HISTORY_LIMIT = 8
_PILLAR_MOVE_THRESHOLD = 2


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_paid(user: User) -> bool:
    return user.plan != UserPlan.free


def _done_audits(db: Session, business_id: int, limit: int = _HISTORY_LIMIT) -> list[Audit]:
    """Most recent completed audits, newest first."""
    return (
        db.query(Audit)
        .filter(Audit.business_id == business_id, Audit.status == AuditStatus.done)
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .limit(limit)
        .all()
    )


def _overall(audit: Audit) -> int | None:
    scores = [s.score for s in audit.sections if s.score is not None]
    return round(sum(scores) / len(scores)) if scores else None


def _maps_raw(audit: Audit) -> dict[str, Any]:
    for sec in audit.sections:
        if sec.section == AuditSectionName.maps:
            return sec.raw_data_json or {}
    return {}


def _weeks_between(a: datetime | None, b: datetime | None) -> int:
    if a is None or b is None:
        return 0
    return max(0, round(abs((b - a).days) / 7))


# --- the lead beat (self-trajectory — shared by index + full report) ---------


def _score_history(audits_desc: list[Audit]) -> list[dict[str, Any]]:
    """Chronological [{date, score}] for the score chart / trajectory."""
    out: list[dict[str, Any]] = []
    for a in reversed(audits_desc):  # oldest → newest
        score = _overall(a)
        if score is not None:
            out.append({"date": a.finished_at, "score": score})
    return out


def _lead(history: list[dict[str, Any]], business_name: str) -> dict[str, Any]:
    """The hero beat: where the business's own visibility stands and which way
    it's trending. Always non-empty (it's about standing, not change)."""
    if not history:
        return {
            "headline": "Your first read is on its way.",
            "sub": "Run a health check and your story starts here.",
            "tone": "neutral",
        }

    latest = history[-1]["score"]
    if len(history) == 1:
        return {
            "headline": f"Your first read is in — {business_name} is at {latest}/100.",
            "sub": "This is your baseline. Every check from here tells you which way you're moving.",
            "tone": "positive",
        }

    earliest = history[0]["score"]
    prev = history[-2]["score"]
    span_weeks = _weeks_between(history[0]["date"], history[-1]["date"])
    prior_max = max(p["score"] for p in history[:-1])
    is_best = latest > prior_max

    if is_best:
        when = f"your best in {span_weeks} weeks" if span_weeks >= 2 else "your best yet"
        return {
            "headline": f"{latest}/100 — {when}. 🎉",
            "sub": (
                f"Up {latest - earliest} since we started watching."
                if latest > earliest
                else "You're at the top of your range — let's push the ceiling."
            ),
            "tone": "positive",
        }

    delta = latest - prev
    if delta >= 2:
        return {
            "headline": f"You climbed to {latest}/100 this week.",
            "sub": f"Up {delta} from last check — momentum's on your side.",
            "tone": "positive",
        }
    if delta <= -2:
        return {
            "headline": f"You eased to {latest}/100 this week.",
            "sub": "A small step back — there's one clear move to turn it around below.",
            "tone": "soft",
        }
    return {
        "headline": f"Holding steady at {latest}/100.",
        "sub": "Quiet week on your own numbers — so let's look at where you can gain.",
        "tone": "neutral",
    }


# --- the other beats (full report only) --------------------------------------


def _trajectory(history: list[dict[str, Any]], detail: dict) -> dict[str, Any]:
    pillars: list[dict[str, Any]] = []
    for sec in detail.get("sections", []):
        if not sec.get("enabled", True):
            continue
        score = sec.get("score")
        prev = sec.get("previous_score")
        delta = (score - prev) if (score is not None and prev is not None) else None
        pillars.append(
            {
                "label": sec.get("label") or sec.get("section"),
                "emoji": sec.get("emoji"),
                "score": score,
                "delta": delta,
                "trend": sec.get("trend"),
            }
        )
    # Biggest movers first (None deltas sink to the bottom).
    pillars.sort(key=lambda p: abs(p["delta"]) if p["delta"] is not None else -1, reverse=True)
    return {"points": history, "pillars": pillars}


def _growth(audits_desc: list[Audit]) -> dict[str, Any] | None:
    """Review trajectory: this period's move + cumulative since we started."""
    series: list[tuple[datetime | None, int]] = []
    for a in reversed(audits_desc):
        rc = _maps_raw(a).get("review_count")
        if isinstance(rc, int):
            series.append((a.finished_at, rc))
    if not series:
        return None
    reviews_now = series[-1][1]
    first = series[0][1]
    prev = series[-2][1] if len(series) > 1 else None
    latest_audit = audits_desc[0]
    rating = _maps_raw(latest_audit).get("rating")
    return {
        "reviews_now": reviews_now,
        "reviews_delta": (reviews_now - prev) if prev is not None else None,
        "reviews_total_gained": reviews_now - first,
        "rating": rating,
        "points": [{"date": d, "reviews": r} for d, r in series],
    }


def _standing(db: Session, business: Business, audits_desc: list[Audit]) -> dict[str, Any]:
    """Competitive position on reviews — the secondary peak. Always framed so a
    user who's behind sees a target, not a verdict."""
    competitors = (
        db.query(Competitor)
        .filter(Competitor.business_id == business.id, Competitor.archived_at.is_(None))
        .all()
    )
    user_reviews = _maps_raw(audits_desc[0]).get("review_count") if audits_desc else None

    rivals: list[dict[str, Any]] = []
    for c in competitors:
        latest_obs = (
            db.query(CompetitorObservation)
            .filter(CompetitorObservation.competitor_id == c.id)
            .order_by(desc(CompetitorObservation.observed_at), desc(CompetitorObservation.id))
            .first()
        )
        if latest_obs is None or latest_obs.review_count is None:
            continue
        rivals.append({"name": c.name, "reviews": latest_obs.review_count})

    if not rivals or not isinstance(user_reviews, int):
        return {"has_competitors": False}

    # Rank the user among {you + rivals} by review count (1 = most reviews).
    everyone = sorted(
        [{"name": "You", "reviews": user_reviews, "is_you": True}]
        + [{**r, "is_you": False} for r in rivals],
        key=lambda x: x["reviews"],
        reverse=True,
    )
    total = len(everyone)
    rank = next(i for i, e in enumerate(everyone, start=1) if e["is_you"])
    ahead_of = [e["name"] for e in everyone if not e["is_you"] and e["reviews"] < user_reviews]
    leader = everyone[0]

    if rank == 1:
        summary = f"You lead all {total - 1} competitors we track on reviews."
        tone = "positive"
    elif ahead_of:
        summary = f"You're #{rank} of {total} — ahead of {len(ahead_of)} of your rivals."
        tone = "positive"
    else:
        gap = leader["reviews"] - user_reviews
        summary = f"You're #{rank} of {total}. {leader['name']} leads by {gap} reviews — that's the target."
        tone = "soft"

    return {
        "has_competitors": True,
        "rank": rank,
        "total": total,
        "you_reviews": user_reviews,
        "leaderboard": everyone[:6],
        "ahead_of_count": len(ahead_of),
        "summary": summary,
        "tone": tone,
    }


def _effort(detail: dict, audits_desc: list[Audit]) -> dict[str, Any]:
    fixes_shipped = 0
    for sec in detail.get("sections", []):
        for rec in sec.get("recommendations", []):
            if rec.get("fix_status") == "done":
                fixes_shipped += 1
    confirmed = len((detail.get("since_last_check") or {}).get("confirmed") or [])
    first = audits_desc[-1].finished_at if audits_desc else None
    latest = audits_desc[0].finished_at if audits_desc else None
    return {
        "fixes_shipped": fixes_shipped,
        "fixes_confirmed_period": confirmed,
        "weeks_monitored": max(1, _weeks_between(first, latest)) if len(audits_desc) > 1 else 1,
        "checkins": len(audits_desc),
    }


def _lever(detail: dict) -> dict[str, Any] | None:
    rank = {"high": 0, "medium": 1, "low": 2}
    candidates: list[dict] = []
    for sec in detail.get("sections", []):
        if not sec.get("enabled", True):
            continue
        for rec in sec.get("recommendations", []):
            if rec.get("fix_status") == "open":
                candidates.append({**rec, "_label": sec.get("label")})
    if not candidates:
        return None
    candidates.sort(key=lambda r: (rank.get(r.get("severity"), 9), r.get("id") or 0))
    top = candidates[0]
    return {
        "title": top.get("title"),
        "section": top.get("section"),
        "section_label": top.get("_label") or top.get("section"),
        "severity": top.get("severity"),
        "estimated_time": top.get("estimated_time"),
        "estimated_impact": top.get("estimated_impact"),
        "id": top.get("id"),
    }


def _pride(business: Business, audits_desc: list[Audit]) -> dict[str, Any]:
    """The "look how far we've come" closer — non-invasive framing of how long
    we've been watching + how many check-ins."""
    first = audits_desc[-1].finished_at if audits_desc else business.added_at
    days = max(1, (_now() - first).days) if first else 1
    return {
        "days_watching": days,
        "checkins": len(audits_desc),
        "since": first,
    }


# --- assembly ----------------------------------------------------------------


def build_report(
    db: Session,
    business: Business,
    user: User,
    audit_id: int | None = None,
) -> dict[str, Any] | None:
    """Assemble the full Weekly Insights report for one business.

    Returns ``None`` when there's no completed audit yet. Tier-gated: free
    users get the cover, the lead, the pride closer, their trajectory chart,
    and a locked TOC; paid users get every beat.
    """
    audits_desc = _done_audits(db, business.id)
    if not audits_desc:
        return None

    if audit_id is not None:
        target = next((a for a in audits_desc if a.id == audit_id), None)
        if target is None:
            t = db.get(Audit, audit_id)
            if t is None or t.business_id != business.id or t.status != AuditStatus.done:
                return None
            target = t
        # Re-window history so it ends at the selected audit.
        audits_desc = [a for a in audits_desc if a.finished_at <= (target.finished_at or _now())]
        if target not in audits_desc:
            audits_desc = [target, *audits_desc]
    else:
        target = audits_desc[0]

    detail = build_audit_detail(db, target)
    history = _score_history(audits_desc)
    paid = _is_paid(user)

    cover = {
        "business": {"id": business.id, "name": business.name, "city": business.city},
        "period_end": target.finished_at,
        "is_first": len(history) <= 1,
    }
    lead = _lead(history, business.name)
    pride = _pride(business, audits_desc)

    base: dict[str, Any] = {
        "audit_id": target.id,
        "tier": "paid" if paid else "free",
        "cover": cover,
        "lead": lead,
        "pride": pride,
        "score": history[-1]["score"] if history else None,
    }

    # Trajectory (the week-by-week chart) is the one beat free users keep:
    # it's the return hook that builds the weekly habit. Everything that
    # follows — growth, standing, effort, the priority fix — stays paid.
    base["trajectory"] = _trajectory(history, detail)

    if not paid:
        # The honest taste: real lead + pride + their own progress chart, and
        # a true menu of what's still locked (with real teaser numbers).
        growth = _growth(audits_desc)
        standing = _standing(db, business, audits_desc)
        locked: list[str] = []
        if growth:
            locked.append(f"Your review growth ({growth['reviews_total_gained']:+d} tracked)")
        if standing.get("has_competitors"):
            locked.append(f"Where you rank vs {standing['total'] - 1} competitors")
        locked.append("Your priority fix this week")
        locked.append("Your progress milestones")
        base["locked"] = {"count": len(locked), "sections": locked}
        return base

    # Paid: every remaining beat.
    base["growth"] = _growth(audits_desc)
    base["standing"] = _standing(db, business, audits_desc)
    base["effort"] = _effort(detail, audits_desc)
    base["lever"] = _lever(detail)
    return base


def build_report_index(db: Session, user: User) -> dict[str, Any]:
    """Lightweight list of the user's businesses with a lead headline each —
    powers the multi-business switcher (Max). Single-business users skip
    straight to the report; this still backs that case cheaply.
    """
    active = (
        db.query(Business)
        .filter(Business.user_id == user.id, Business.archived_at.is_(None))
        .order_by(Business.added_at)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for biz in active:
        audits_desc = _done_audits(db, biz.id)
        if not audits_desc:
            continue
        history = _score_history(audits_desc)
        lead = _lead(history, biz.name)
        rows.append(
            {
                "business": {"id": biz.id, "name": biz.name, "city": biz.city},
                "audit_id": audits_desc[0].id,
                "period_end": audits_desc[0].finished_at,
                "score": history[-1]["score"] if history else None,
                "lead_headline": lead["headline"],
            }
        )
    return {"tier": "paid" if _is_paid(user) else "free", "businesses": rows}
