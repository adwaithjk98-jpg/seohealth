"""Suite 2 — tier limits + quota windows (MONEY_TESTS_SPEC.md).

The gates the whole free→paid boundary rests on: discovery 402/429, the audit
weekly window, per-tier caps, and the ``== free`` (never ``!= paid``) rule that
the Max-tier launch bug taught us. Services are called directly — the HTTP
shape is asserted on the raised HTTPException.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

import app.services.discovery_scan as discovery_service
from app.api.audits import _audit_usage_this_week
from app.models import DiscoveryScan
from app.models.enums import DiscoveryScanStatus
from app.services import subscriptions as subs
from app.services.discovery_scan import assert_can_run, count_scans_this_month

from tests.conftest import AuditStatus, UserPlan


def _add_scan(db, user, *, status, when):
    db.add(
        DiscoveryScan(
            user_id=user.id,
            query="cafes in kochi",
            num_leads=5,
            fields_csv="name",
            status=status,
            requested_at=when,
        )
    )
    db.flush()


# --- 7. Free user is 402'd (paid-only) --------------------------------------

def test_free_user_discovery_scan_402(db, make_user):
    user = make_user(plan=UserPlan.free)
    with pytest.raises(HTTPException) as exc:
        assert_can_run(db, user)
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "discovery_scan_paid_only"


# --- 8. Paid user at monthly limit → 429 with next_reset = 1st of next month -

def test_paid_user_at_limit_429_december_rollover(db, make_user, monkeypatch):
    # Freeze near a year boundary to exercise the Dec→Jan branch of the window.
    frozen = datetime(2026, 12, 20, 10, 0, 0)
    monkeypatch.setattr(discovery_service, "_now_naive", lambda: frozen)

    user = make_user(plan=UserPlan.paid)  # limit = 1/month
    _add_scan(db, user, status=DiscoveryScanStatus.done, when=datetime(2026, 12, 5))

    with pytest.raises(HTTPException) as exc:
        assert_can_run(db, user)
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "discovery_scan_monthly_limit"
    # Next reset is the 1st of January 2027 (rollover branch).
    assert exc.value.detail["next_reset_at"].startswith("2027-01-01")


# --- 9. Quota counts pending+running+done, excludes failed (F4) -------------

def test_scan_quota_excludes_failed_counts_the_rest(db, make_user, monkeypatch):
    frozen = datetime(2026, 7, 15, 10, 0, 0)
    monkeypatch.setattr(discovery_service, "_now_naive", lambda: frozen)
    user = make_user(plan=UserPlan.max)  # limit = 4

    _add_scan(db, user, status=DiscoveryScanStatus.done, when=datetime(2026, 7, 2))
    _add_scan(db, user, status=DiscoveryScanStatus.running, when=datetime(2026, 7, 3))
    _add_scan(db, user, status=DiscoveryScanStatus.pending, when=datetime(2026, 7, 4))
    _add_scan(db, user, status=DiscoveryScanStatus.failed, when=datetime(2026, 7, 5))
    _add_scan(db, user, status=DiscoveryScanStatus.failed, when=datetime(2026, 7, 6))

    # 3 counted (done+running+pending), 2 failed refunded.
    assert count_scans_this_month(db, user) == 3
    # A prior-month done scan doesn't count toward this month.
    _add_scan(db, user, status=DiscoveryScanStatus.done, when=datetime(2026, 6, 30))
    assert count_scans_this_month(db, user) == 3


def test_failed_scans_do_not_block_a_max_user(db, make_user, monkeypatch):
    frozen = datetime(2026, 7, 15, 10, 0, 0)
    monkeypatch.setattr(discovery_service, "_now_naive", lambda: frozen)
    user = make_user(plan=UserPlan.max)  # limit = 4
    for day in (2, 3, 4, 5, 6):  # 5 failed scans this month
        _add_scan(db, user, status=DiscoveryScanStatus.failed, when=datetime(2026, 7, day))
    # All refunded → still allowed to run.
    assert_can_run(db, user)  # does not raise


# --- 10. Gates test == free, not != paid (the Max-tier lesson) --------------

def test_max_user_passes_the_free_gate(db, make_user):
    """A Max user must NOT be treated as free. If the gate said `!= paid` it
    would wrongly 402 the Max user (whose plan is `max`, not `paid`)."""
    user = make_user(plan=UserPlan.max)
    assert_can_run(db, user)  # no exception — Max is allowed discovery


# --- 11. Free audit weekly window (rolling 7 days), failed excluded ---------

def test_free_audit_weekly_window(db, make_user, make_business, make_audit):
    user = make_user(plan=UserPlan.free)  # 2 audits/week
    biz = make_business(user)
    now = datetime.utcnow()
    # Two done audits inside the window → at the cap.
    for days_ago in (1, 2):
        a = make_audit(biz, sections=[], status=AuditStatus.done)
        a.started_at = now - timedelta(days=days_ago)
    db.flush()
    used, _ = _audit_usage_this_week(db, user.id)
    assert used == 2
    limit = subs.TIER_LIMITS[user.plan]["audits_per_week"]
    assert used >= limit  # would be 429'd on the next create


def test_failed_audit_is_refunded_from_weekly_window(db, make_user, make_business, make_audit):
    user = make_user(plan=UserPlan.free)
    biz = make_business(user)
    now = datetime.utcnow()
    ok = make_audit(biz, sections=[], status=AuditStatus.done)
    ok.started_at = now - timedelta(days=1)
    bad = make_audit(biz, sections=[], status=AuditStatus.failed)
    bad.started_at = now - timedelta(days=1)
    db.flush()
    # Only the done one counts; the failed one is refunded.
    used, _ = _audit_usage_this_week(db, user.id)
    assert used == 1


# --- 12. Per-tier caps -------------------------------------------------------

def test_tier_caps_match_the_pricing_model(make_user):
    free = make_user(plan=UserPlan.free)
    paid = make_user(plan=UserPlan.paid)
    mx = make_user(plan=UserPlan.max)
    assert subs.user_competitor_limit(free) == 0
    assert subs.user_competitor_limit(paid) == 4
    assert subs.user_competitor_limit(mx) == 8
    assert subs.user_business_limit(free) == 1
    assert subs.user_business_limit(paid) == 1
    assert subs.user_business_limit(mx) == 5
    assert subs.user_discovery_scan_monthly_limit(free) == 0
    assert subs.user_discovery_scan_monthly_limit(paid) == 1
    assert subs.user_discovery_scan_monthly_limit(mx) == 4


def test_business_cap_blocks_over_limit(db, make_user, make_business):
    user = make_user(plan=UserPlan.paid)  # 1 business
    make_business(user)
    assert subs.can_user_add_business(db, user) is False
    mx = make_user(plan=UserPlan.max)  # 5 businesses
    make_business(mx)
    assert subs.can_user_add_business(db, mx) is True
