"""Suite 3 — Razorpay webhook transitions (MONEY_TESTS_SPEC.md).

Signature verification is exercised for real (HMAC-SHA256 over the raw body) via
TestClient; the state transitions are driven through ``handle_webhook_event``
directly. Includes the **W2** guard: a retried/out-of-order ``charged`` after a
cancellation must NOT resurrect paid access.
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.enums import SubscriptionStatus, UserPlan
from app.services import subscriptions as subs


def _event(event_type: str, sub_id: str) -> dict:
    return {
        "event": event_type,
        "payload": {"subscription": {"entity": {"id": sub_id}}},
    }


def _charged(db, user, sub_id="sub_test_1", tier="paid"):
    """Seed a past_due row and fire its first charged event → active."""
    subs._mark_past_due(db, user, sub_id, tier)
    return subs.handle_webhook_event(db, _event("subscription.charged", sub_id))


# --- 14. activate: free→paid, idempotent on redelivery ----------------------

def test_charged_activates_then_idempotent(db, make_user):
    user = make_user(plan=UserPlan.free)
    res = _charged(db, user)
    assert res["status"] == "active"
    assert user.plan == UserPlan.paid

    # Redeliver the same event — terminal state unchanged, no error, one row.
    subs.handle_webhook_event(db, _event("subscription.charged", "sub_test_1"))
    assert user.plan == UserPlan.paid
    rows = [s for s in db.query(subs.Subscription).filter_by(user_id=user.id)]
    assert len(rows) == 1
    assert rows[0].status == SubscriptionStatus.active


# --- 15. cancelled → free ----------------------------------------------------

def test_cancelled_reverts_to_free(db, make_user):
    user = make_user(plan=UserPlan.free)
    _charged(db, user)
    subs.handle_webhook_event(db, _event("subscription.cancelled", "sub_test_1"))
    assert user.plan == UserPlan.free


# --- 16. halted/completed treated as cancel (pin current behaviour) ---------

@pytest.mark.parametrize("event_type", ["subscription.halted", "subscription.completed"])
def test_halted_and_completed_cancel(db, make_user, event_type):
    user = make_user(plan=UserPlan.free)
    _charged(db, user)
    res = subs.handle_webhook_event(db, _event(event_type, "sub_test_1"))
    assert res["status"] == "cancelled"
    assert user.plan == UserPlan.free


# --- 17. unknown subscription id → handled:False, no crash ------------------

def test_unknown_subscription_id_ignored(db, make_user):
    res = subs.handle_webhook_event(db, _event("subscription.charged", "sub_never_seen"))
    assert res["handled"] is False
    assert "unknown" in res["reason"]


# --- 18. plan_tier → UserPlan mapping doesn't crash on max -------------------

def test_max_tier_mapping(db, make_user):
    user = make_user(plan=UserPlan.free)
    _charged(db, user, sub_id="sub_max_1", tier="max")
    assert user.plan == UserPlan.max


# --- W2. charged-after-cancel must NOT resurrect ----------------------------

def test_w2_charged_after_cancel_does_not_resurrect(db, make_user):
    user = make_user(plan=UserPlan.free)
    _charged(db, user)                                            # active/paid
    subs.handle_webhook_event(db, _event("subscription.cancelled", "sub_test_1"))
    assert user.plan == UserPlan.free                             # cancelled/free

    # A delayed/retried charged event arrives AFTER the cancellation.
    res = subs.handle_webhook_event(db, _event("subscription.charged", "sub_test_1"))
    assert res["handled"] is False
    assert "cancelled" in res["reason"]
    # The row stays cancelled and the user stays free — no free ride.
    row = db.query(subs.Subscription).filter_by(razorpay_subscription_id="sub_test_1").one()
    assert row.status == SubscriptionStatus.cancelled
    assert user.plan == UserPlan.free


# --- 13. Signature verification through the real endpoint -------------------

def _client(db, monkeypatch):
    monkeypatch.setattr(subs.settings, "razorpay_webhook_secret", "whsec_test")

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_bad_signature_rejected_plan_unchanged(db, make_user, monkeypatch):
    user = make_user(plan=UserPlan.free)
    _mark = subs._mark_past_due(db, user, "sub_sig", "paid")  # noqa: F841
    client = _client(db, monkeypatch)
    try:
        body = json.dumps(_event("subscription.charged", "sub_sig")).encode()
        r = client.post(
            "/api/subscriptions/webhook",
            content=body,
            headers={"X-Razorpay-Signature": "deadbeef", "Content-Type": "application/json"},
        )
        assert r.status_code == 400
        assert user.plan == UserPlan.free  # never activated
    finally:
        app.dependency_overrides.clear()


def test_good_signature_accepted(db, make_user, monkeypatch):
    user = make_user(plan=UserPlan.free)
    subs._mark_past_due(db, user, "sub_sig2", "paid")
    client = _client(db, monkeypatch)
    try:
        body = json.dumps(_event("subscription.charged", "sub_sig2")).encode()
        sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        r = client.post(
            "/api/subscriptions/webhook",
            content=body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "active"
        assert user.plan == UserPlan.paid
    finally:
        app.dependency_overrides.clear()
