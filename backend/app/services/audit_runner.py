import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Audit,
    AuditSection,
    Business,
    Competitor,
    CompetitorObservation,
    Recommendation,
    User,
)
from app.models.enums import (
    AuditSectionName,
    AuditSectionStatus,
    AuditStatus,
    RecommendationFixStatus,
    RecommendationSeverity,
    UserPlan,
)
from app.services import audit_events
from app.services.email_service import (
    SCORE_CHANGE_NOTIFY_THRESHOLD,
    send_score_change_email,
)
from app.services.prune_old_data import prune_old_audit_data
from scrapers import (
    CompetitorMetrics,
    audit_instagram,
    audit_maps,
    audit_nap,
    audit_website,
    fetch_competitor_metrics,
)
from scrapers.types import BusinessInput, SectionResult

logger = logging.getLogger(__name__)

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


def _previous_overall_score(
    db: Session, business_id: int, current_audit_id: int
) -> int | None:
    """Overall score (mean of non-null section scores) for the most recent
    completed audit before this one. ``None`` if no prior completed audit
    exists — first-ever audit has nothing to compare against.
    """
    prev = (
        db.query(Audit)
        .filter(
            Audit.business_id == business_id,
            Audit.id != current_audit_id,
            Audit.status == AuditStatus.done,
        )
        .order_by(desc(Audit.finished_at), desc(Audit.id))
        .first()
    )
    if prev is None:
        return None
    scores = [s.score for s in prev.sections if s.score is not None]
    return round(sum(scores) / len(scores)) if scores else None


def _maybe_notify_score_change(
    db: Session,
    business: Business,
    current_audit_id: int,
    new_score: int,
) -> None:
    """Fire a score-change email when the new overall differs from the
    previous completed audit by more than the notify threshold.

    Failures are logged and swallowed: an audit run is already a long-tailed
    operation and a flaky email provider shouldn't take the run with it.
    """
    previous = _previous_overall_score(db, business.id, current_audit_id)
    if previous is None:
        # First-ever completed audit — no baseline to compare against.
        return
    if abs(new_score - previous) <= SCORE_CHANGE_NOTIFY_THRESHOLD:
        return
    user = db.get(User, business.user_id)
    if user is None:
        return
    dashboard_url = (
        f"{settings.frontend_base_url.rstrip('/')}/businesses/{business.id}"
    )
    try:
        send_score_change_email(
            to_email=user.email,
            business_name=business.name,
            previous_score=previous,
            new_score=new_score,
            dashboard_url=dashboard_url,
        )
    except Exception:
        logger.exception(
            "score-change email failed for audit_id=%s business_id=%s",
            current_audit_id,
            business.id,
        )


def _active_competitors(db: Session, business_id: int) -> list[Competitor]:
    return (
        db.query(Competitor)
        .filter(
            Competitor.business_id == business_id,
            Competitor.archived_at.is_(None),
        )
        .order_by(Competitor.id)
        .all()
    )


def _persist_competitor_observations(
    db: Session,
    audit_id: int,
    metrics: list[CompetitorMetrics],
) -> None:
    """Insert one row per competitor scraped during this audit.

    We persist even when ``rating`` / ``review_count`` came back ``None`` so
    the trend chart can show "we tried on this date" rather than a gap that
    could be confused with the competitor being un-tracked at the time.
    """
    if not metrics:
        return
    now = datetime.now(timezone.utc)
    for m in metrics:
        db.add(
            CompetitorObservation(
                competitor_id=m.competitor_id,
                audit_id=audit_id,
                rating=m.rating,
                review_count=m.review_count,
                observed_at=now,
            )
        )
    db.commit()


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

        # Phase 4 — competitor tracking. Paid-only, runs after the main
        # pipeline so a competitor scraping failure can't tank the user's
        # own audit score. Free users are explicitly skipped (we don't even
        # enumerate their competitors row — there shouldn't be any).
        user = db.get(User, business.user_id)
        if user is not None and user.plan == UserPlan.paid:
            competitors = _active_competitors(db, business.id)
            tracked = [(c.id, c.maps_url) for c in competitors if c.maps_url]
            if tracked:
                await stream.publish(
                    {
                        "type": "competitors_started",
                        "count": len(tracked),
                    }
                )
                competitor_progress = _make_progress_cb("competitors")
                try:
                    metrics = await fetch_competitor_metrics(
                        tracked, progress=competitor_progress
                    )
                    _persist_competitor_observations(db, audit_id, metrics)
                    await stream.publish(
                        {
                            "type": "competitors_completed",
                            "observed": len(metrics),
                        }
                    )
                except Exception as exc:
                    logger.exception(
                        "competitor scraping failed for audit_id=%s", audit_id
                    )
                    await stream.publish(
                        {
                            "type": "competitors_failed",
                            "error": repr(exc),
                        }
                    )

        overall = round(sum(section_scores) / len(section_scores)) if section_scores else 0
        audit = db.get(Audit, audit_id)
        audit.status = AuditStatus.done
        audit.finished_at = datetime.now(timezone.utc)
        db.commit()

        # Phase 3 — fire a "your score changed" email if the overall moved
        # meaningfully vs. the previous completed audit. Runs after the row
        # is marked ``done`` so the email's dashboard link points at a fully
        # persisted audit. Swallows its own errors.
        _maybe_notify_score_change(db, business, audit_id, overall)

        # Opportunistic storage pruning — NULLs heavy raw_data_json payloads
        # on audits older than the retention window so Postgres doesn't
        # balloon as audit volume grows. The rq-scheduler also runs this on
        # a daily cron; firing it here means storage stays trimmed even when
        # the scheduler process is down. Idempotent + cheap (single UPDATE).
        try:
            prune_old_audit_data(db)
        except Exception:
            logger.exception(
                "prune_old_audit_data failed after audit_id=%s", audit_id
            )

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
