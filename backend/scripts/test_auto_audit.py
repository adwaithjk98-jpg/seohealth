"""Manually trigger the auto-audit dispatcher for verification.

Mirrors what rq-scheduler does on its daily tick, but runs in-process so
you can see the dispatch summary printed immediately without waiting on
the cron clock. The dispatcher itself opens its own ``SessionLocal()`` —
this script just calls it and pretty-prints the result.

Useful for:
  * Confirming a paid business that's overdue gets enqueued.
  * Confirming a free business is never enqueued.
  * Confirming an in-flight audit is skipped (no double-enqueue).

Run from ``backend/``:
    .venv/bin/python -m scripts.test_auto_audit
"""
from __future__ import annotations

import json
import logging

from app.services.auto_audit import dispatch_due_audits


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    summary = dispatch_due_audits()
    print("\nauto-audit dispatch summary:")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
