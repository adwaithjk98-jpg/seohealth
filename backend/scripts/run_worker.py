"""Run an RQ worker that processes audit jobs.

Importing ``app.workers.queue`` pulls in ``app.config`` which loads
``backend/.env`` via pydantic-settings, so the worker process gets the
same env (DATABASE_URL, REDIS_URL, AUDIT_*) the API gets — no
``python -m dotenv`` wrapper needed.

Run from ``backend/``:
    .venv/bin/python -m scripts.run_worker
"""
import logging

from rq import Worker

from app.workers.queue import audit_queue, redis_conn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = Worker([audit_queue], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
