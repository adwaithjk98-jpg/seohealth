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
from app.models import DiscoveryScan
from app.models.enums import DiscoveryScanStatus
from app.services.competitor_cache import upsert_metric_cache
from app.services.competitor_scraper_adapter import (
    CompetitorScraperError,
    run_competitor_scrape,
)
from scrapers import fetch_competitor_metrics

logger = logging.getLogger(__name__)


def refresh_cache_job(cache_key: str, maps_url: str) -> dict[str, str | float | None]:
    """Scrape one URL with Selenium and UPSERT the cache row.

    Returns a small dict so the RQ result store and log show what actually
    landed (rating + review_count + any error). Designed to never raise on
    a normal scrape failure — the cache row's ``last_error`` column records
    that for diagnostics. Only infrastructure errors (DB down) bubble up so
    RQ retries / dead-letters them.
    """
    db = SessionLocal()
    try:
        metrics = asyncio.run(fetch_competitor_metrics([(0, maps_url)]))
        if not metrics:
            logger.warning(
                "refresh_cache_job: scraper returned no results for url=%r", maps_url
            )
            return {"cache_key": cache_key, "status": "no_result"}
        metric = metrics[0]
        upsert_metric_cache(db, cache_key, maps_url, metric)
        db.commit()
        return {
            "cache_key": cache_key,
            "rating": metric.rating,
            "review_count": metric.review_count,
            "error": metric.error,
        }
    finally:
        db.close()


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

        scan.status = DiscoveryScanStatus.done
        scan.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        scan.result_count = len(result.results)
        scan.results_json = result.results
        db.commit()

        return {
            "scan_id": scan_id,
            "status": "done",
            "result_count": len(result.results),
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
