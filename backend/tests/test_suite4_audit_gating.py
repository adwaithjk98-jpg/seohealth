"""Suite 4 — audit status gating + quota refund (MONEY_TESTS_SPEC.md).

The crash-recovery invariant (22) is tested for real against this test's DB.
Test 20 (failed audit → weekly quota refunded) lives in Suite 2
(``test_failed_audit_is_refunded_from_weekly_window``) since it's a property of
the same ``_audit_usage_this_week`` window. Tests 19/21/23 exercise decisions
made *inside* the async ``run_audit_job`` pipeline (Maps-spine gate, non-spine
soft-fail, carried check-marks); they need a scraper-mocking pipeline harness
and are marked as tracked skips rather than faked.
"""
from sqlalchemy.orm import sessionmaker

import pytest

from app.models import Audit
from app.workers import queue as queue_mod

from tests.conftest import AuditStatus


# --- 22. on_audit_job_failure flips a running audit to failed ---------------

def test_on_failure_hook_marks_running_audit_failed(
    db, make_user, make_business, make_audit, monkeypatch
):
    """A signal-level worker death (OOM/SIGKILL) leaves the runner no chance to
    write status; RQ's on_failure callback is the last line of defence against
    a row stuck at 'running'. Drive it directly with a fabricated job."""
    user = make_user()
    biz = make_business(user)
    audit = make_audit(biz, sections=[], status=AuditStatus.running)
    db.commit()  # durable setup: the hook opens a *separate* session
    audit_id = audit.id

    # The hook opens its own SessionLocal — point it at this test's DB (same
    # in-memory engine, so the commit is visible to our fixture session).
    monkeypatch.setattr("app.db.SessionLocal", sessionmaker(bind=db.bind))

    class FakeJob:
        args = [audit_id]

    class FakeConn:
        def xadd(self, *a, **k):
            return None

        def expire(self, *a, **k):
            return None

    queue_mod.on_audit_job_failure(
        FakeJob(), FakeConn(), ValueError, ValueError("worker OOM"), None
    )

    db.expire_all()
    refreshed = db.get(Audit, audit_id)
    assert refreshed.status == AuditStatus.failed
    assert refreshed.error_message  # a terminal reason is recorded


def test_on_failure_hook_does_not_touch_terminal_audit(
    db, make_user, make_business, make_audit, monkeypatch
):
    """Idempotent against the in-process handler: if the runner already marked
    the audit done, a late on_failure callback must not clobber it to failed."""
    user = make_user()
    biz = make_business(user)
    audit = make_audit(biz, sections=[], status=AuditStatus.done)
    db.commit()  # durable setup
    audit_id = audit.id
    monkeypatch.setattr("app.db.SessionLocal", sessionmaker(bind=db.bind))

    class FakeJob:
        args = [audit_id]

    class FakeConn:
        def xadd(self, *a, **k):
            return None

        def expire(self, *a, **k):
            return None

    queue_mod.on_audit_job_failure(
        FakeJob(), FakeConn(), ValueError, ValueError("late crash"), None
    )
    db.expire_all()
    assert db.get(Audit, audit_id).status == AuditStatus.done


# --- 19 / 21 / 23 — need the async pipeline harness (tracked, not faked) -----

@pytest.mark.skip(reason="needs run_audit_job pipeline harness w/ mocked scrapers")
def test_19_maps_spine_failure_fails_audit():
    """Maps (the spine) fails-to-measure → audit status='failed', not 'done'."""


@pytest.mark.skip(reason="needs run_audit_job pipeline harness w/ mocked scrapers")
def test_21_non_spine_failure_stays_done_with_none_section():
    """PageSpeed/IG timeout → audit still 'done', that section score=None,
    overall computed from the rest (the aggregation half is covered in Suite 1)."""


@pytest.mark.skip(reason="needs run_audit_job pipeline harness w/ mocked scrapers")
def test_23_carried_checkmarks_survive_failed_reaudit():
    """Carried 'done' check-marks + verify_signal fix-verification survive a
    failed re-audit (no wiping user progress on infra failure)."""
