"""Run rq-scheduler — the cron clock for Phase 3 auto-audits + data pruning.

What it does
------------
On startup, registers two recurring jobs:

    * cron: ``"0 6 * * *"`` (daily 06:00 UTC)
      func: ``app.services.auto_audit.dispatch_due_audits``
    * cron: ``"0 7 * * *"`` (daily 07:00 UTC)
      func: ``app.services.prune_old_data.prune_old_audit_data``
      (NULLs the heavy ``raw_data_json`` payload on audits >30d old —
      keeps Postgres storage flat as audit volume grows)

Both share queue ``audits`` (the same one the API and worker consume).

Then it blocks in ``scheduler.run()``, polling Redis for due jobs and
enqueueing them into the audits queue. The existing RQ worker picks them
up and executes the dispatcher, which in turn enqueues per-business
``run_audit_job``\\s.

This is a separate long-running process (alongside ``uvicorn`` and
``scripts.run_worker``). It owns no DB connections of its own — the
dispatch function opens / closes ``SessionLocal()`` once per tick.

Run from ``backend/``:
    .venv/bin/python -m scripts.run_scheduler

Idempotency note
----------------
rq-scheduler persists scheduled jobs in Redis, so restarting this process
without cleanup would multiply the cron registration. On startup we cancel
any existing schedule for the dispatcher before re-adding it.
"""
from __future__ import annotations

import logging

from rq_scheduler import Scheduler

from app.workers.queue import audit_queue, competitor_queue, redis_conn

logger = logging.getLogger(__name__)

_DISPATCH_FUNC = "app.services.auto_audit.dispatch_due_audits"
_PRUNE_FUNC = "app.services.prune_old_data.prune_old_audit_data"
_COMPETITOR_REFRESH_FUNC = "app.services.competitor_refresh.refresh_due_competitors"
# Daily at 06:00 UTC — early-morning IST. The cadence per business is
# enforced inside the dispatcher; this just decides how often we *check*.
_CRON_STRING = "0 6 * * *"
# Daily at 07:00 UTC — runs an hour after the dispatcher so the prune
# sweep doesn't contend with a flurry of freshly-enqueued audits. The
# pruner itself is just an UPDATE so the offset is comfort, not correctness.
_PRUNE_CRON_STRING = "0 7 * * *"
# Daily at 02:00 UTC (~07:30 IST) — well before the morning auto-audit
# tick at 06:00 UTC, so by the time those audits run their tracked
# competitors are already warm in the global cache. Routed to the
# low-priority queue and drained by ``scripts.run_competitor_worker``.
_COMPETITOR_REFRESH_CRON_STRING = "0 2 * * *"

# Funcs we own a cron for — keeps the "cancel before re-add" loop
# generic so adding more crons later is a one-line change.
_MANAGED_FUNCS = (_DISPATCH_FUNC, _PRUNE_FUNC, _COMPETITOR_REFRESH_FUNC)


def _clear_existing(scheduler: Scheduler) -> int:
    """Cancel any pre-existing schedule for the functions we manage.

    rq-scheduler stores cron registrations in Redis, so without this a
    container restart would silently double-register every cron.
    """
    removed = 0
    for job in scheduler.get_jobs():
        if job.func_name in _MANAGED_FUNCS:
            scheduler.cancel(job)
            removed += 1
    return removed


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    scheduler = Scheduler(queue=audit_queue, connection=redis_conn)
    removed = _clear_existing(scheduler)
    if removed:
        logger.info("cleared %s stale managed schedule(s) from Redis", removed)
    scheduler.cron(
        _CRON_STRING,
        func=_DISPATCH_FUNC,
        queue_name=audit_queue.name,
        repeat=None,
    )
    scheduler.cron(
        _PRUNE_CRON_STRING,
        func=_PRUNE_FUNC,
        queue_name=audit_queue.name,
        repeat=None,
    )
    # Phase 4 — off-peak competitor cache refresh. Routed to the low-priority
    # queue so it's drained by the dedicated competitor worker, not the
    # audits worker. Live API traffic and self-audits stay unaffected even
    # if every tracked competitor happens to come due on the same morning.
    scheduler.cron(
        _COMPETITOR_REFRESH_CRON_STRING,
        func=_COMPETITOR_REFRESH_FUNC,
        queue_name=competitor_queue.name,
        repeat=None,
    )
    logger.info(
        "scheduler registered (dispatch_cron=%r prune_cron=%r competitor_refresh_cron=%r queues=[%s, %s]); entering run loop",
        _CRON_STRING,
        _PRUNE_CRON_STRING,
        _COMPETITOR_REFRESH_CRON_STRING,
        audit_queue.name,
        competitor_queue.name,
    )
    scheduler.run()


if __name__ == "__main__":
    main()
