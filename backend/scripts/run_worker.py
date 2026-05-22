"""Run an RQ worker that processes audit jobs.

Importing ``app.workers.queue`` pulls in ``app.config`` which loads
``backend/.env`` via pydantic-settings, so the worker process gets the
same env (DATABASE_URL, REDIS_URL, AUDIT_*) the API gets — no
``python -m dotenv`` wrapper needed.

Run from ``backend/``:
    .venv/bin/python -m scripts.run_worker
"""
import os
import sys

# macOS forks the work-horse for each job. Anything that has already
# touched Objective-C runtime initialisation in the parent (e.g.
# urllib, ssl, certain CPython internals) will SIGABRT the child with
# "+[NSNumber initialize] may have been in progress" unless this
# disable flag is set before fork(). Harmless on Linux.
if sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

import logging

from rq import SimpleWorker, Worker

from app.workers.queue import audit_queue, redis_conn

# On macOS, the work-horse fork() crashes when a parent thread has touched
# the Objective-C runtime (Selenium / requests / ssl all do, transitively).
# OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES no longer rescues us on recent
# macOS versions, so on darwin we run jobs in-process via SimpleWorker.
# On Linux (prod), fork() is fine and Worker gives us crash isolation.
_WorkerCls = SimpleWorker if sys.platform == "darwin" else Worker


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = _WorkerCls([audit_queue], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
