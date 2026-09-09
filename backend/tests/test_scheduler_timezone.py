"""The scheduler's cron strings must mean UTC, whatever the host timezone is.

Every cron in ``scripts/run_scheduler.py`` is written and documented in UTC
("Mondays 03:30 UTC (~09:00 IST)"), but rq_scheduler resolves a cron string
against a naive ``datetime.now()`` — i.e. local wall-clock — and only then
re-expresses the result in UTC. So the documented times are correct only while
the process's local timezone happens to be UTC.

Production gets that for free (python:3.12-slim-bookworm has no /etc/localtime),
which is exactly what makes the bug easy to reintroduce: it is invisible until
someone sets TZ on the box or in compose to get IST log timestamps, at which
point every schedule silently shifts by 5h30 and the Monday-morning digest goes
out at 03:30 IST. ``run_scheduler`` therefore pins TZ=UTC itself.

This runs in a subprocess under a deliberately hostile TZ, because the fix is a
process-global ``time.tzset()`` — asserting it in-process would both contaminate
the rest of the suite and not actually prove the entrypoint does it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# UTC+5:30 — the offset the owner develops in, and the one most likely to get
# set on the box. The half-hour offset also catches a subtler failure than a
# whole-hour zone would: an hourly "0 * * * *" cron still fires hourly under
# IST, just at HH:30 UTC instead of HH:00.
HOSTILE_TZ = "Asia/Kolkata"

_PROBE = textwrap.dedent(
    """
    # Importing the entrypoint is what should pin the timezone.
    import scripts.run_scheduler  # noqa: F401
    from rq_scheduler.utils import get_next_scheduled_time

    for cron in ("30 3 * * 1", "0 7 * * *", "0 * * * *"):
        t = get_next_scheduled_time(cron)
        print(f"{cron}|{t.hour:02d}:{t.minute:02d}")
    """
)


def _run_probe(tz: str) -> dict[str, str]:
    env = {**os.environ, "TZ": tz, "PYTHONPATH": str(BACKEND_DIR)}
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, f"probe failed:\n{out.stdout}\n{out.stderr}"
    return dict(
        line.split("|", 1) for line in out.stdout.strip().splitlines() if "|" in line
    )


def test_weekly_digest_fires_at_0330_utc_under_a_hostile_tz():
    """The one with a user-visible consequence: 03:30 UTC is 09:00 IST.

    Read as local time in IST it becomes 03:30 IST — a 3:30am email, which
    defeats the entire stated point of the Monday digest.
    """
    assert _run_probe(HOSTILE_TZ)["30 3 * * 1"] == "03:30"


def test_daily_prune_fires_at_0700_utc_under_a_hostile_tz():
    assert _run_probe(HOSTILE_TZ)["0 7 * * *"] == "07:00"


def test_hourly_dispatch_fires_on_the_utc_hour_under_a_hostile_tz():
    """Guards the auto-audit hour-buckets.

    ``dispatch_due_audits`` only fires businesses where ``id % 24 == now.hour``
    with ``now`` in UTC. Under IST the tick lands at HH:30 UTC, which still
    gives one tick per UTC hour and so still works — but only by luck. A
    whole-hour offset zone would shift the bucket and strand businesses.
    """
    assert _run_probe(HOSTILE_TZ)["0 * * * *"].endswith(":00")


def test_schedule_is_identical_regardless_of_host_timezone():
    """The actual invariant: the host's TZ must not change the schedule."""
    assert _run_probe(HOSTILE_TZ) == _run_probe("UTC")
