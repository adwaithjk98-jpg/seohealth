"""Assembles the full audit-detail payload returned by the dashboard APIs.

The dashboard's three layers all read from a single endpoint:

* Layer 1 (Glance) needs the overall score + per-section score & summary.
* Layer 2 (Section detail) needs the same plus sub-checks + recommendations.
* Layer 3 (Guided fix) reads recommendation fields directly.

Rather than building three different endpoints, we return everything together
— the payload is small (one audit, ~10 recommendations) and the UI is fully
client-rendered, so a single fetch keeps state simple.
"""

from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import Audit, Business, Recommendation
from app.models.audit_section import AuditSection
from app.models.enums import AuditStatus
from app.services.audit_summary import (
    derive_sub_checks,
    grade_from_score,
    section_meta,
    section_summary,
)


SECTION_ORDER = ["maps", "website", "instagram", "nap", "competitors"]


# Trend cutoff — score has to move at least this much to count as up/down.
# A 1-point wobble between audits isn't worth flagging.
TREND_THRESHOLD = 2


def _trend(current: int | None, previous: int | None) -> str | None:
    if current is None or previous is None:
        return None
    diff = current - previous
    if diff >= TREND_THRESHOLD:
        return "up"
    if diff <= -TREND_THRESHOLD:
        return "down"
    return "flat"


def _previous_section_scores(
    db: Session, business_id: int, current_audit_id: int
) -> tuple[dict[str, int | None], int | None]:
    """Returns ({section_name: score}, overall_score) for the most recent
    completed audit for this business, excluding the current audit.
    """
    prev_audit = (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.id != current_audit_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .first()
    )
    if prev_audit is None:
        return {}, None
    by_section: dict[str, int | None] = {}
    scores: list[int] = []
    for sec in prev_audit.sections:
        by_section[sec.section.value] = sec.score
        if sec.score is not None:
            scores.append(sec.score)
    overall = round(sum(scores) / len(scores)) if scores else None
    return by_section, overall


def build_audit_detail(db: Session, audit: Audit) -> dict:
    business = db.get(Business, audit.business_id)
    sections: list[AuditSection] = list(audit.sections)
    recommendations: list[Recommendation] = list(audit.recommendations)

    # Group recommendations by section.
    recs_by_section: dict[str, list[Recommendation]] = {}
    for rec in recommendations:
        recs_by_section.setdefault(rec.section.value, []).append(rec)

    # Order recommendations within a section by severity then by id.
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    for sec, recs in recs_by_section.items():
        recs.sort(key=lambda r: (severity_rank.get(r.severity.value, 99), r.id))

    prev_section_scores, prev_overall = _previous_section_scores(
        db, audit.business_id, audit.id
    )

    section_payloads = []
    section_scores: list[int] = []
    for sec in sections:
        meta = section_meta(sec.section.value)
        score = sec.score
        sub_checks = derive_sub_checks(sec.section.value, sec.raw_data_json)
        summary = section_summary(sec.section.value, sec.raw_data_json)
        sec_recs = recs_by_section.get(sec.section.value, [])
        prev_score = prev_section_scores.get(sec.section.value)

        section_payloads.append(
            {
                "section": sec.section.value,
                "label": meta["label"],
                "emoji": meta["emoji"],
                "tagline": meta["tagline"],
                "score": score,
                "grade": grade_from_score(score),
                "status": sec.status.value,
                "summary": summary,
                "raw_data": sec.raw_data_json,
                "sub_checks": sub_checks,
                "previous_score": prev_score,
                "trend": _trend(score, prev_score),
                "recommendations": [
                    _recommendation_payload(r) for r in sec_recs
                ],
            }
        )
        if score is not None:
            section_scores.append(score)

    # Sort sections in plan-defined display order.
    section_payloads.sort(
        key=lambda s: SECTION_ORDER.index(s["section"]) if s["section"] in SECTION_ORDER else 999
    )

    overall_score: int | None = (
        round(sum(section_scores) / len(section_scores)) if section_scores else None
    )

    open_count = sum(1 for r in recommendations if r.fix_status.value == "open")
    done_count = sum(1 for r in recommendations if r.fix_status.value == "done")

    return {
        "audit_id": audit.id,
        "business": {
            "id": business.id,
            "name": business.name,
            "city": business.city,
            "country": business.country,
        }
        if business is not None
        else {"id": audit.business_id, "name": "", "city": "", "country": ""},
        "status": audit.status.value,
        "trigger": audit.trigger.value,
        "started_at": audit.started_at,
        "finished_at": audit.finished_at,
        "overall_score": overall_score,
        "overall_grade": grade_from_score(overall_score),
        "previous_overall_score": prev_overall,
        "overall_trend": _trend(overall_score, prev_overall),
        "sections": section_payloads,
        "open_recommendations_count": open_count,
        "done_recommendations_count": done_count,
    }


def _recommendation_payload(rec: Recommendation) -> dict:
    return {
        "id": rec.id,
        "section": rec.section.value,
        "severity": rec.severity.value,
        "title": rec.title,
        "body_markdown": rec.body_markdown,
        "estimated_impact": rec.estimated_impact,
        "estimated_time": rec.estimated_time,
        "fix_status": rec.fix_status.value,
        "marked_done_at": rec.marked_done_at,
    }
