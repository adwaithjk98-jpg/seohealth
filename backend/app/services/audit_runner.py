from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Audit, AuditSection, Business, Recommendation
from app.models.enums import (
    AuditSectionName,
    AuditSectionStatus,
    AuditStatus,
    RecommendationFixStatus,
    RecommendationSeverity,
)
from app.services import audit_events
from scrapers import audit_instagram, audit_maps, audit_nap, audit_website
from scrapers.types import BusinessInput, SectionResult

ScraperFn = Callable[[BusinessInput], Awaitable[SectionResult]]

PIPELINE: list[tuple[AuditSectionName, ScraperFn]] = [
    (AuditSectionName.maps, audit_maps),
    (AuditSectionName.website, audit_website),
    (AuditSectionName.instagram, audit_instagram),
    (AuditSectionName.nap, audit_nap),
]


def _to_business_input(business: Business) -> BusinessInput:
    return BusinessInput(
        name=business.name,
        city=business.city,
        country=business.country,
        maps_url=business.maps_url,
        website=business.website,
        ig_handle=business.ig_handle,
    )


def _persist_section(
    db: Session, audit_id: int, section: AuditSectionName, result: SectionResult
) -> None:
    db.add(
        AuditSection(
            audit_id=audit_id,
            section=section,
            score=result.score,
            status=AuditSectionStatus(result.status),
            raw_data_json=result.raw_data,
        )
    )
    for rec in result.recommendations:
        db.add(
            Recommendation(
                audit_id=audit_id,
                section=section,
                severity=RecommendationSeverity(rec.severity),
                title=rec.title,
                body_markdown=rec.body_markdown,
                estimated_impact=rec.estimated_impact,
                estimated_time=rec.estimated_time,
                fix_status=RecommendationFixStatus.open,
            )
        )
    db.commit()


async def run_audit(audit_id: int) -> None:
    stream = audit_events.get_or_create_stream(audit_id)
    db = SessionLocal()
    try:
        audit = db.get(Audit, audit_id)
        if audit is None:
            await stream.publish({"type": "audit_failed", "error": "audit not found"})
            return

        business = db.get(Business, audit.business_id)
        if business is None:
            audit.status = AuditStatus.failed
            audit.error_message = "business not found"
            audit.finished_at = datetime.now(timezone.utc)
            db.commit()
            await stream.publish({"type": "audit_failed", "error": "business not found"})
            return

        audit.status = AuditStatus.running
        db.commit()
        await stream.publish(
            {
                "type": "audit_started",
                "audit_id": audit_id,
                "business": {"id": business.id, "name": business.name, "city": business.city},
                "sections": [s.value for s, _ in PIPELINE],
            }
        )

        business_input = _to_business_input(business)
        section_scores: list[int] = []

        for section, scraper in PIPELINE:
            await stream.publish({"type": "section_started", "section": section.value})
            try:
                result = await scraper(business_input)
            except Exception as exc:
                db.add(
                    AuditSection(
                        audit_id=audit_id,
                        section=section,
                        score=None,
                        status=AuditSectionStatus.failed,
                        raw_data_json={"error": str(exc)},
                    )
                )
                db.commit()
                await stream.publish(
                    {
                        "type": "section_completed",
                        "section": section.value,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            _persist_section(db, audit_id, section, result)
            # A scraper can return SectionResult(status="failed") for soft failures
            # (CAPTCHA, missing input, etc.) — keep those out of the overall average
            # so a missing Instagram handle doesn't tank an otherwise-healthy score.
            if result.status != AuditSectionStatus.failed.value:
                section_scores.append(result.score)
            await stream.publish(
                {
                    "type": "section_completed",
                    "section": section.value,
                    "status": result.status,
                    "score": result.score,
                    "recommendation_count": len(result.recommendations),
                    "summary": result.raw_data,
                }
            )

        overall = round(sum(section_scores) / len(section_scores)) if section_scores else 0
        audit = db.get(Audit, audit_id)
        audit.status = AuditStatus.done
        audit.finished_at = datetime.now(timezone.utc)
        db.commit()

        await stream.publish(
            {
                "type": "audit_completed",
                "audit_id": audit_id,
                "overall_score": overall,
                "section_count": len(section_scores),
            }
        )
    except Exception as exc:
        audit = db.get(Audit, audit_id)
        if audit is not None:
            audit.status = AuditStatus.failed
            audit.error_message = repr(exc)
            audit.finished_at = datetime.now(timezone.utc)
            db.commit()
        await stream.publish({"type": "audit_failed", "error": repr(exc)})
        raise
    finally:
        await stream.close()
        db.close()
