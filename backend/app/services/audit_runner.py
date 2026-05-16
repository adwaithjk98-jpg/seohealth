import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
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

# Fields a scraper is allowed to fill in on the Business row mid-pipeline.
# Anything outside this allowlist is ignored — keeps a misbehaving scraper
# from quietly mutating user-owned columns (city, name, etc.).
_DISCOVERABLE_FIELDS: frozenset[str] = frozenset({"website", "ig_handle"})

ScraperFn = Callable[[BusinessInput], Awaitable[SectionResult]]

PIPELINE: list[tuple[AuditSectionName, ScraperFn]] = [
    (AuditSectionName.maps, audit_maps),
    (AuditSectionName.website, audit_website),
    (AuditSectionName.instagram, audit_instagram),
    (AuditSectionName.nap, audit_nap),
]


# Recommendations don't have a stable id across audits — each audit produces a
# fresh set. To carry "marked done" forward, we match by (section, title) on
# the previous completed audit for the same business.
def _previous_done_titles(
    db: Session, business_id: int, current_audit_id: int
) -> set[tuple[str, str]]:
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
        return set()
    done = (
        db.query(Recommendation)
        .filter(
            Recommendation.audit_id == prev_audit.id,
            Recommendation.fix_status == RecommendationFixStatus.done,
        )
        .all()
    )
    return {(r.section.value, r.title) for r in done}


def _to_business_input(business: Business) -> BusinessInput:
    return BusinessInput(
        name=business.name,
        city=business.city,
        country=business.country,
        maps_url=business.maps_url,
        website=business.website,
        ig_handle=business.ig_handle,
    )


def _apply_discovered_fields(
    db: Session, business: Business, discovered: dict[str, str | None]
) -> bool:
    """Fill null Business columns from a scraper's discovered_fields.

    Per-field, null-only: a value typed by the user in the form always wins.
    Returns True if any column was updated (so the caller can refresh inputs).
    """
    changed = False
    for field_name, value in discovered.items():
        if field_name not in _DISCOVERABLE_FIELDS:
            continue
        if not value:
            continue
        if getattr(business, field_name, None):
            continue
        setattr(business, field_name, value)
        changed = True
    if changed:
        db.commit()
        db.refresh(business)
    return changed


def _persist_section(
    db: Session,
    audit_id: int,
    section: AuditSectionName,
    result: SectionResult,
    carried_done_titles: set[tuple[str, str]],
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
    now = datetime.now(timezone.utc)
    for rec in result.recommendations:
        already_done = (section.value, rec.title) in carried_done_titles
        db.add(
            Recommendation(
                audit_id=audit_id,
                section=section,
                severity=RecommendationSeverity(rec.severity),
                title=rec.title,
                body_markdown=rec.body_markdown,
                estimated_impact=rec.estimated_impact,
                estimated_time=rec.estimated_time,
                fix_status=(
                    RecommendationFixStatus.done
                    if already_done
                    else RecommendationFixStatus.open
                ),
                marked_done_at=now if already_done else None,
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
        carried_done_titles = _previous_done_titles(db, business.id, audit_id)
        # NAP needs to compare against earlier sections' raw_data; we keep a
        # running map keyed by section name and pass it as a second arg below.
        prior_raw: dict[str, dict] = {}

        # Built per-section so the progress events carry the right section name
        # without each scraper having to know its own slug.
        loop = asyncio.get_running_loop()

        def _make_progress_cb(section_name: str):
            """Return a sync callback the scraper invokes from any thread.

            Scrapers run in a worker thread (asyncio.to_thread), so the
            callback bridges back into the running loop via
            ``call_soon_threadsafe`` rather than touching the stream
            directly. Best-effort: if publishing fails we swallow it so
            a flaky bus doesn't tank a real audit run.
            """

            def _cb(step: str, detail: dict | None = None) -> None:
                event = {
                    "type": "section_progress",
                    "section": section_name,
                    "step": step,
                    "detail": detail or {},
                }
                try:
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(stream.publish(event))
                    )
                except RuntimeError:
                    # Loop is shutting down; intermediate narration isn't
                    # important enough to take down the audit for.
                    pass

            return _cb

        for section, scraper in PIPELINE:
            await stream.publish({"type": "section_started", "section": section.value})
            progress_cb = _make_progress_cb(section.value)
            try:
                # NAP has a different signature (takes prior_results) — it's
                # the only scraper that needs cross-section context, so we
                # special-case it rather than widening the ScraperFn typedef.
                if section == AuditSectionName.nap:
                    result = await scraper(business_input, prior_raw)
                else:
                    # Scrapers that accept a progress callback (Maps, etc.)
                    # narrate sub-steps; older ones that don't are called
                    # without it. We sniff via the parameter list so adding
                    # callbacks to other scrapers needs no runner changes.
                    sig = inspect.signature(scraper)
                    if "progress" in sig.parameters:
                        result = await scraper(business_input, progress=progress_cb)  # type: ignore[call-arg]
                    else:
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

            _persist_section(db, audit_id, section, result, carried_done_titles)
            prior_raw[section.value] = result.raw_data or {}
            if result.discovered_fields and _apply_discovered_fields(
                db, business, result.discovered_fields
            ):
                business_input = _to_business_input(business)
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
