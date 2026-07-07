import asyncio
import inspect
import logging
import random
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
    Recommendation,
    User,
)
from app.models.enums import (
    AuditSectionName,
    AuditSectionStatus,
    AuditStatus,
    AuditTrigger,
    RecommendationFixStatus,
    RecommendationSeverity,
)
from app.services import audit_events, push_service
from app.services.email_service import (
    SCORE_CHANGE_NOTIFY_THRESHOLD,
    send_score_change_email,
)
from app.services.pillar_optout import enabled_pillars
from app.services.prune_old_data import prune_old_audit_data
from app.services.section_highlight import section_highlight
from scrapers import (
    audit_instagram,
    audit_maps,
    audit_nap,
    audit_pagespeed,
    audit_website,
)
from scrapers.types import BusinessInput, SectionResult

logger = logging.getLogger(__name__)

# Fields a scraper is allowed to fill in on the Business row mid-pipeline.
# Anything outside this allowlist is ignored — keeps a misbehaving scraper
# from quietly mutating user-owned columns (city, name, etc.).
_DISCOVERABLE_FIELDS: frozenset[str] = frozenset(
    {"website", "ig_handle", "google_place_id"}
)

ScraperFn = Callable[[BusinessInput], Awaitable[SectionResult]]

PIPELINE: list[tuple[AuditSectionName, ScraperFn]] = [
    (AuditSectionName.maps, audit_maps),
    (AuditSectionName.website, audit_website),
    # Performance runs right after website: it needs the same website URL
    # (incl. one Maps may have just discovered) and reads naturally in the
    # live feed as "checked your site → measured how fast it loads".
    (AuditSectionName.performance, audit_pagespeed),
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
        google_place_id=business.google_place_id,
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


def _previous_section_snapshots(
    db: Session, business_id: int, current_audit_id: int
) -> dict[str, dict]:
    """Per-section scoreboard for the most recent prior completed audit.

    Returns ``{section_name: {"score": int|None, "raw": dict|None}}`` so
    the live-feed renderer can compare each pillar against last time
    ("Reviews up 8 since last check"). Empty dict when this is the first
    audit for the business — the frontend treats absent prev-data as
    "first-time orientation" framing.
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
        return {}
    out: dict[str, dict] = {}
    for sec in prev.sections:
        out[sec.section.value] = {
            "score": sec.score,
            "raw": sec.raw_data_json or None,
        }
    return out


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
    # Matches the live run's rule: include all sections (skipped /
    # soft-failed ones contribute their 0). Previously this excluded
    # ``failed`` sections to avoid phantom drops in the score-change
    # notification, but that hid real "still missing your website"
    # signals from the user. Symmetry with the live calc matters more
    # than notification quietness — the threshold check below filters
    # out tiny moves anyway.
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


def _maybe_push_scheduled_audit_done(
    db: Session,
    business: Business,
    audit: Audit,
    overall: int,
) -> None:
    """Web-push the owner when a *scheduled* audit finishes.

    Only scheduled runs notify — a user who kicked off a manual audit is
    already watching the live feed, so a push would be redundant noise. The
    audit is already committed ``done`` by the time we get here, so a flaky
    push service can't affect the run; errors are logged and swallowed.
    """
    if audit.trigger != AuditTrigger.scheduled:
        return
    # A little variety so the weekly nudge doesn't read like the same robot
    # every time. Each variant is a (title, body) pair — all warm, and all
    # point the owner at *what changed* rather than just announcing "done"
    # (a teaser for the recap, not a dead notification).
    name = business.name
    variants = [
        (
            "Your check-up's in ✨",
            f"{name} is at {overall}/100 this week. Tap to see what moved.",
        ),
        (
            "Fresh audit, fresh read 🌿",
            f"We just re-checked {name} — you're sitting at {overall}/100. "
            "Here's what changed.",
        ),
        (
            "This week's read is ready 📊",
            f"{name}'s scheduled check-up is done ({overall}/100). "
            "See the one thing worth a few minutes.",
        ),
    ]
    title, body = random.choice(variants)
    try:
        push_service.send_to_user(
            db,
            business.user_id,
            title=title,
            body=body,
            url=f"/businesses/{business.id}",
        )
    except Exception:
        logger.exception(
            "scheduled-audit push failed for audit_id=%s business_id=%s",
            audit.id,
            business.id,
        )


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
                # Default the target to the emitting section — true for
                # every scraper except NAP, which sets its own per-rec
                # target so cross-pillar findings can be filtered by
                # opt-out at read time.
                fix_target=rec.fix_target or section.value,
                # Stable key for the fix-loop verifier. NULL when the
                # scraper didn't tag this rec (NAP cross-source recs,
                # anything ambiguous) — those stay outside the auto-
                # verification flow.
                verify_signal=rec.verify_signal,
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
        # Snapshot of the previous audit's per-section scores + raw_data.
        # Used to enrich each ``section_completed`` event with a "+8
        # reviews since last check" headline, and to flip the
        # audit_started copy between first-audit ("getting to know
        # you") and returning-user ("re-checking ...") modes.
        prev_snapshots = _previous_section_snapshots(db, business.id, audit_id)
        is_first_audit = len(prev_snapshots) == 0
        await stream.publish(
            {
                "type": "audit_started",
                "audit_id": audit_id,
                "business": {"id": business.id, "name": business.name, "city": business.city},
                "sections": [s.value for s, _ in PIPELINE],
                "is_first_audit": is_first_audit,
            }
        )

        business_input = _to_business_input(business)
        section_scores: list[int] = []
        section_outcomes: dict[AuditSectionName, str] = {}
        carried_done_titles = _previous_done_titles(db, business.id, audit_id)
        # NAP needs to compare against earlier sections' raw_data; we keep a
        # running map keyed by section name and pass it as a second arg below.
        prior_raw: dict[str, dict] = {}
        # Pillars the business has opted *out* of via the FTUE
        # questionnaire. We skip their scrapers entirely (saving the
        # round-trip) and persist a placeholder failed/0 row so the
        # audit shape is preserved — the read path then filters these
        # out of the dashboard grid + overall score by section name.
        enabled_set = enabled_pillars(business)

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
            # FTUE opt-out: persist a 0/failed placeholder and move on
            # without spending a network round-trip. ``enabled_pillars``
            # already enforces "Maps can't be opted out" and "NAP needs
            # >=2 other sources," so the only sections that actually
            # land here are ``website`` / ``instagram`` (when the user
            # said no) and ``nap`` (when both website + instagram are
            # off, which leaves nothing to compare).
            if section.value not in enabled_set:
                db.add(
                    AuditSection(
                        audit_id=audit_id,
                        section=section,
                        score=0,
                        status=AuditSectionStatus.failed,
                        raw_data_json={"opted_out": True},
                    )
                )
                db.commit()
                section_outcomes[section] = "failed"
                await stream.publish(
                    {
                        "type": "section_completed",
                        "section": section.value,
                        "status": "failed",
                        "opted_out": True,
                        # Skipped-by-design pillars get a distinct
                        # headline so the live feed shows why they're
                        # absent ("Skipped — you said you don't use a
                        # website") instead of looking broken.
                        "highlight": "Skipped — you opted out of this pillar",
                    }
                )
                # Don't feed into prior_raw — NAP must see it as absent.
                # Don't append 0 to section_scores either — the runner's
                # honest-overall principle stays intact; the read path
                # is the one that drops opted-out pillars from the avg.
                continue
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
                section_outcomes[section] = "failed"
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
            section_outcomes[section] = result.status
            # Only feed *successful* sections into the NAP comparison's
            # prior_raw. A skipped Maps section has no phone/address to
            # compare against — including it caused NAP to generate
            # "we couldn't find your phone on Google Maps" findings against
            # sources that were never actually checked.
            if result.status != AuditSectionStatus.failed.value:
                prior_raw[section.value] = result.raw_data or {}
            if result.discovered_fields and _apply_discovered_fields(
                db, business, result.discovered_fields
            ):
                business_input = _to_business_input(business)
            # Score is averaged across all four sections. Skipped /
            # soft-failed sections (no website provided, no IG handle,
            # etc.) contribute their score as-is — the scrapers already
            # return ``score=0`` for these cases, and that's the honest
            # read: if we couldn't verify website + Instagram for a
            # business, the user's overall health *should* reflect that
            # they have work to do, not silently round up by excluding
            # the gaps. Used to skip ``failed`` sections, which made
            # half-empty audits read as 85/100 — misleading, since the
            # per-section "Skipped" cards already prompt the user to
            # fix the underlying data.
            #
            # ``score is None`` is distinct from ``score == 0``: it means the
            # section couldn't be measured at all (e.g. IG account isn't a
            # Business/Creator profile), so it's *excluded* from the average
            # rather than dragging it to 0 — mirroring the read path in
            # audit_view and ``_previous_overall_score``.
            if result.score is not None:
                section_scores.append(result.score)
            prev_snap = prev_snapshots.get(section.value, {})
            await stream.publish(
                {
                    "type": "section_completed",
                    "section": section.value,
                    "status": result.status,
                    "score": result.score,
                    "recommendation_count": len(result.recommendations),
                    "summary": result.raw_data,
                    # Live-diff payload. ``previous_score`` enables the
                    # "was 65, +5" delta chip; ``highlight`` is a short
                    # newsy headline ("8 new reviews since last check")
                    # computed by section_highlight from this run's
                    # raw_data and the previous audit's raw_data.
                    "previous_score": prev_snap.get("score"),
                    "highlight": section_highlight(
                        section.value,
                        result.raw_data,
                        prev_snap.get("raw"),
                    ),
                }
            )

        # Competitor scraping is no longer coupled to user-triggered
        # audits. As of the 2026-05-26 architectural shift, competitor
        # observations are written exclusively by the weekly
        # ``competitor_refresh`` cron (see ``services/competitor_refresh.py``).
        # Reasons: (a) user audits should be about the user's own business
        # only — coupling competitor scrape made every audit much heavier;
        # (b) decoupling means competitor trend points keep landing on a
        # predictable cadence even in weeks the user doesn't audit;
        # (c) the audit pipeline's failure modes (CAPTCHA, slow Maps) no
        # longer cascade into competitor-side noise. The historical
        # ``competitors_started`` / ``competitors_completed`` stream events
        # are gone with the block.

        overall = round(sum(section_scores) / len(section_scores)) if section_scores else 0
        audit = db.get(Audit, audit_id)

        # An audit only counts as ``done`` if Maps actually loaded — it's
        # the spine of the audit (name/address/reviews come from there,
        # and the website + IG scrapers depend on what it discovered).
        # NAP runs on whatever earlier sections collected, so it can
        # "succeed" even when nothing else did; relying on overall
        # status=done was masking audits where Maps failed and the user
        # saw a confident-looking score derived from one stub section.
        # Website / Instagram are allowed to fail (the business may not
        # have them yet) — those failures are visible per-section in the
        # dashboard and don't invalidate the overall read.
        maps_outcome = section_outcomes.get(AuditSectionName.maps)
        if maps_outcome != "done":
            audit.status = AuditStatus.failed
            audit.error_message = (
                "We couldn't reach your Google Maps listing — please "
                "double-check the business name and city, or paste the "
                "Maps URL on the Edit business page, then try again."
            )
            audit.finished_at = datetime.now(timezone.utc)
            db.commit()
            await stream.publish(
                {
                    "type": "audit_failed",
                    "error": audit.error_message,
                    "audit_id": audit_id,
                }
            )
            return

        audit.status = AuditStatus.done
        audit.finished_at = datetime.now(timezone.utc)
        db.commit()

        # Phase 3 — fire a "your score changed" email if the overall moved
        # meaningfully vs. the previous completed audit. Runs after the row
        # is marked ``done`` so the email's dashboard link points at a fully
        # persisted audit. Swallows its own errors.
        _maybe_notify_score_change(db, business, audit_id, overall)

        # Web-push the owner when a *scheduled* audit completes (manual runs are
        # already on-screen in the live feed). Best-effort, like the email above.
        _maybe_push_scheduled_audit_done(db, business, audit, overall)

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
