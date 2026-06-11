"""RQ job functions for the low-priority ``competitor_jobs`` queue.

Two kinds of work land here:

* ``refresh_cache_job(cache_key, maps_url)`` — fired by the daily cron in
  ``services.competitor_refresh``. Scrapes one Maps URL with the in-process
  Selenium fetcher and UPSERTs the result into ``competitor_metric_cache``.
  No observations are written: observations belong to an audit, and the
  whole point of the cache is to let the *next* audit serve this URL for
  free instead of re-scraping.

* ``discovery_scan_job(scan_id)`` — fired by the API when a paid user kicks
  off a Discovery Scan. Loads the ``discovery_scans`` row, shells out to
  ``audit_scraper`` via the adapter, and writes results + status back.

Both run on the dedicated competitor worker process (``run_competitor_worker``)
so a 10-minute Selenium discovery run can't share a CPU with a user's live
self-audit.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import Business, Competitor, CompetitorObservation, DiscoveryScan
from app.models.enums import DiscoveryScanStatus
from app.services import push_service
from app.services.competitor_cache import normalize_maps_url, upsert_metric_cache
from app.services.competitor_scraper_adapter import (
    CompetitorScraperError,
    run_competitor_scrape,
)
from scrapers import audit_instagram, fetch_competitor_metrics
from scrapers.maps import CompetitorScrapeTarget
from scrapers.types import BusinessInput

logger = logging.getLogger(__name__)

# A tracked competitor gaining at least this many Google reviews since our last
# observation is worth a "they're pulling ahead" push to the owner. Mirrors the
# score-change email's threshold philosophy: only notify on a real move.
COMPETITOR_REVIEW_NOTIFY_DELTA = 3


def _ig_handle_from_url(url: str | None) -> str | None:
    """Extract an Instagram handle from a profile URL.

    ``https://www.instagram.com/brewmorphia/?utm_source=…`` → ``brewmorphia``.
    Returns None for anything that doesn't look like an instagram.com URL
    (e.g. the user pasted a Facebook link by mistake).
    """
    if not url:
        return None
    lower = url.lower()
    if "instagram.com/" not in lower:
        return None
    tail = url.split("instagram.com/", 1)[1]
    tail = tail.split("?", 1)[0].split("#", 1)[0].strip("/").strip()
    # Strip any sub-paths (``/reel/...``, ``/p/...``); we want the handle only.
    handle = tail.split("/", 1)[0]
    return handle.lstrip("@") or None


async def _ig_metrics_for_url(url: str | None) -> tuple[int | None, int | None]:
    """Pull ``(followers, post_count)`` for a competitor's IG URL.

    Reuses ``scrapers.audit_instagram`` so we don't reimplement the
    og:description parsing. Returns ``(None, None)`` on any failure
    (no handle, profile gated, parse miss) — the caller writes those
    as null observation fields without aborting the surrounding refresh.
    """
    handle = _ig_handle_from_url(url)
    if not handle:
        return None, None
    try:
        result = await audit_instagram(
            BusinessInput(name="competitor", city="", country="", ig_handle=handle)
        )
        raw = result.raw_data or {}
        followers = raw.get("followers")
        posts = raw.get("post_count")
        return (
            int(followers) if isinstance(followers, (int, float)) else None,
            int(posts) if isinstance(posts, (int, float)) else None,
        )
    except Exception:
        logger.exception("ig scrape failed for url=%r", url)
        return None, None


def refresh_cache_job(cache_key: str, maps_url: str) -> dict[str, str | float | None]:
    """Refresh one Maps URL: scrape, UPSERT cache, write observation rows.

    This is the weekly competitor-data tick. Previously it only updated
    the global ``CompetitorMetricCache`` (per-URL dedup across users) —
    as of 2026-05-26 it also writes one ``CompetitorObservation`` row
    per active competitor on this URL, so the trend chart picks up a
    new point each week independent of any user-triggered audit. IG
    follower/post counts are scraped per-competitor too when the row
    has an ``instagram_url`` on file (Maps URL is one-to-many with
    Competitor rows; IG handles can differ across users tracking the
    same listing, so we scrape per row).

    Designed to never raise on a normal scrape failure — failed bits
    land in the cache row's ``last_error`` column or as null
    observation fields. Only infrastructure errors (DB down) bubble.
    """
    db = SessionLocal()
    try:
        # Find every active Competitor row that maps to this cache_key.
        # We can't normalize in SQL portably; load active rows and filter.
        # (Done up-front now so we can pass name + parent-city into the
        # scraper as search-by-name input — that's the flow that
        # produces working review_count, mirroring the user-audit path.)
        matching: list[Competitor] = []
        for c in (
            db.query(Competitor)
            .filter(
                Competitor.archived_at.is_(None),
                Competitor.maps_url.is_not(None),
            )
            .all()
        ):
            if normalize_maps_url(c.maps_url or "") == cache_key:
                matching.append(c)

        # Pull a representative name + city for the search query. Many
        # users can track the same listing, but the underlying business
        # is one place — any matching row's name works, and the parent
        # business's city is the right locality hint (competitors are
        # tracked nearby by definition).
        search_name: str | None = None
        search_city: str | None = None
        if matching:
            first = matching[0]
            search_name = first.name
            # Lazy-load the parent business for the city.
            parent = db.get(Business, first.business_id) if first.business_id else None
            if parent is not None:
                search_city = parent.city

        target = CompetitorScrapeTarget(
            competitor_id=0,
            maps_url=maps_url,
            name=search_name,
            city=search_city,
        )
        metrics = asyncio.run(fetch_competitor_metrics([target]))
        if not metrics:
            logger.warning(
                "refresh_cache_job: scraper returned no results for url=%r", maps_url
            )
            return {"cache_key": cache_key, "status": "no_result"}
        metric = metrics[0]
        upsert_metric_cache(db, cache_key, maps_url, metric)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        obs_written = 0
        # (business_id, competitor_name, review_delta) to push *after* commit —
        # we don't want to hold the txn open across the push HTTP calls.
        pending_pushes: list[tuple[int, str | None, int]] = []
        for comp in matching:
            # Self-heal: competitors tracked before the discovery
            # scraper started returning IG/website fields (or added
            # manually via maps_url only) land with NULL URLs. The
            # metric scrape probes the Maps panel for both and exposes
            # them on ``metric``; backfill them onto the Competitor
            # row the first time we see them so future refreshes don't
            # have to re-discover.
            if not comp.website_url and getattr(metric, "website_url", None):
                comp.website_url = metric.website_url
            if not comp.instagram_url and getattr(metric, "instagram_url", None):
                comp.instagram_url = metric.instagram_url
            ig_followers, ig_posts = asyncio.run(
                _ig_metrics_for_url(comp.instagram_url)
            )
            # Snapshot the prior review count *before* writing the new point so
            # we can detect a meaningful jump and nudge the owner.
            prev_reviews = (
                db.query(CompetitorObservation.review_count)
                .filter(CompetitorObservation.competitor_id == comp.id)
                .order_by(
                    CompetitorObservation.observed_at.desc(),
                    CompetitorObservation.id.desc(),
                )
                .limit(1)
                .scalar()
            )
            db.add(
                CompetitorObservation(
                    competitor_id=comp.id,
                    audit_id=None,  # cron-written, not tied to a user audit
                    rating=metric.rating,
                    review_count=metric.review_count,
                    instagram_followers=ig_followers,
                    instagram_posts=ig_posts,
                    observed_at=now,
                )
            )
            obs_written += 1
            if (
                prev_reviews is not None
                and metric.review_count is not None
                and metric.review_count - prev_reviews >= COMPETITOR_REVIEW_NOTIFY_DELTA
            ):
                pending_pushes.append(
                    (comp.business_id, comp.name, metric.review_count - prev_reviews)
                )
        db.commit()

        # Best-effort competitor-moved pushes (after commit so the txn isn't
        # held open across HTTP). No-op in dev / when VAPID is unset.
        for business_id, comp_name, delta in pending_pushes:
            business = db.get(Business, business_id)
            if business is None:
                continue
            try:
                push_service.send_to_user(
                    db,
                    business.user_id,
                    title=f"{comp_name or 'A competitor'} is pulling ahead 👀",
                    body=(
                        f"They just picked up {delta} new reviews. "
                        "See how you stack up."
                    ),
                    url=f"/businesses/{business_id}",
                )
            except Exception:
                logger.exception(
                    "competitor-moved push failed for business_id=%s", business_id
                )

        return {
            "cache_key": cache_key,
            "rating": metric.rating,
            "review_count": metric.review_count,
            "observations_written": obs_written,
            "error": metric.error,
        }
    finally:
        db.close()


def _norm_name(value: str | None) -> str:
    """Collapse whitespace + lowercase for fuzzy name matching."""
    if not value:
        return ""
    return " ".join(value.split()).lower()


def _filter_out_own_roster(
    db, user_id: int, leads: list[dict]
) -> list[dict]:
    """Drop leads that match the user's own businesses or tracked competitors.

    Discovery was happily returning the user's own anchor business as the
    #1 "similar" result — and would do the same with already-tracked
    competitors. Neither is useful. We dedupe on two signals so the
    scraper's variable naming/URL formats don't slip through:

    * ``maps_url`` exact match (after the scraper's own dedup wouldn't
      catch these — the user's row may have a different URL shape).
    * ``name`` normalised (whitespace-collapsed lowercase) match.

    Matching against archived rows on purpose: a user who archived a
    competitor and re-ran discovery probably doesn't want to see them
    pop back up as a "fresh" suggestion.
    """
    blocked_urls: set[str] = set()
    blocked_names: set[str] = set()
    for biz in db.query(Business).filter(Business.user_id == user_id).all():
        if biz.maps_url:
            blocked_urls.add(biz.maps_url)
        blocked_names.add(_norm_name(biz.name))
    business_ids = [b.id for b in db.query(Business).filter(Business.user_id == user_id).all()]
    if business_ids:
        for comp in (
            db.query(Competitor).filter(Competitor.business_id.in_(business_ids)).all()
        ):
            if comp.maps_url:
                blocked_urls.add(comp.maps_url)
            blocked_names.add(_norm_name(comp.name))
    blocked_names.discard("")

    kept: list[dict] = []
    for lead in leads:
        if lead.get("maps_url") and lead["maps_url"] in blocked_urls:
            continue
        if _norm_name(lead.get("name")) in blocked_names:
            continue
        kept.append(lead)
    return kept


def discovery_scan_job(scan_id: int) -> dict[str, int | str]:
    """Execute a queued Discovery Scan and persist the outcome.

    State machine:
      ``pending`` → ``running`` → (``done`` | ``failed``)

    The row is the source of truth for the rate limiter — exiting in any
    terminal state is fine (the limiter counts all rows in the current
    month, not just successful ones). What we must not do is leave a row
    stuck at ``running`` forever, so any exception flips it to ``failed``
    before re-raising for RQ.
    """
    db = SessionLocal()
    try:
        scan = db.get(DiscoveryScan, scan_id)
        if scan is None:
            logger.warning("discovery_scan_job: scan_id=%s not found", scan_id)
            return {"scan_id": scan_id, "status": "missing"}

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        scan.status = DiscoveryScanStatus.running
        scan.started_at = now
        db.commit()

        fields = scan.fields_csv.split(",") if scan.fields_csv else ["name"]

        try:
            result = asyncio.run(
                run_competitor_scrape(
                    query=scan.query,
                    num_leads=scan.num_leads,
                    fields=fields,
                    filters=scan.filters or None,
                )
            )
        except CompetitorScraperError as exc:
            logger.exception(
                "discovery_scan_job: scraper error for scan_id=%s", scan_id
            )
            scan.status = DiscoveryScanStatus.failed
            scan.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            scan.error_message = str(exc)[:1024]
            db.commit()
            raise

        filtered = _filter_out_own_roster(db, scan.user_id, result.results)
        scan.status = DiscoveryScanStatus.done
        scan.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        scan.result_count = len(filtered)
        scan.results_json = filtered
        db.commit()

        return {
            "scan_id": scan_id,
            "status": "done",
            "result_count": len(filtered),
            "dropped_self": len(result.results) - len(filtered),
        }
    except Exception:
        # Catch-all: ensure no row stays at ``running`` if anything unusual
        # raises between checkpoints (DB hiccup, OOM, signal). RQ's
        # ``on_failure`` does similar duty for audits, but this is enough
        # for the simpler scan lifecycle.
        try:
            scan = db.get(DiscoveryScan, scan_id)
            if scan is not None and scan.status == DiscoveryScanStatus.running:
                scan.status = DiscoveryScanStatus.failed
                scan.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                if not scan.error_message:
                    scan.error_message = "worker crashed unexpectedly"
                db.commit()
        except Exception:
            logger.exception(
                "discovery_scan_job: failed to mark scan_id=%s failed", scan_id
            )
        raise
    finally:
        db.close()
