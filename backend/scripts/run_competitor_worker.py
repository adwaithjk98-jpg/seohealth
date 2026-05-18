"""Dedicated RQ worker for the low-priority ``competitor_jobs`` queue.

Why a separate process from ``run_worker``? Two reasons:

1. **Isolation.** Selenium-Chrome holds significant memory and occasionally
   leaks. Pinning the heavy competitor work to its own process keeps a bad
   discovery-scan run from OOM-killing an audit worker mid-Selenium.
2. **Priority.** Audit jobs are user-facing (someone clicked "Run audit").
   Competitor refreshes are background (cron-driven) and Discovery Scans
   are long-running. Running them on separate workers means the audits
   worker can keep draining its queue even when the competitor worker is
   tied up for 10 minutes on a single scan.

Run from ``backend/``:
    .venv/bin/python -m scripts.run_competitor_worker
"""
import logging

from rq import Worker

from app.workers.queue import competitor_queue, redis_conn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = Worker([competitor_queue], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
