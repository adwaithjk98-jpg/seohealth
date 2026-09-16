"""``GET /api/home`` — the consolidated cold-open payload.

The endpoint exists to collapse three serial round trips into one, so what
matters here is that the single payload says *exactly* what the three separate
calls said. The contract worth protecting:

  - it never 401s (signed-out is 200 + ``user: null``), because the SPA's own
    route gate does the redirecting;
  - ``businesses`` is ``null`` when signed out but ``[]`` when signed in with
    none — two different screens, so the frontend must be able to tell them
    apart;
  - ``hero_audit`` is sent only for single-business accounts with a completed
    audit, mirroring what the home screen actually renders;
  - the embedded user/business payloads match ``/auth/session`` and
    ``/businesses`` field-for-field, so a cached home payload can't drift from
    what the rest of the app reads.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.main import app
from app.models.enums import AuditSectionName, AuditStatus, UserPlan
from app.services import auth as auth_service


@pytest.fixture
def client(db):
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sign_in(client, db, user) -> None:
    """Attach a real session cookie to the client, as a browser would."""
    session = auth_service.create_session(db, user)
    client.cookies.set(settings.session_cookie_name, session.token)


# --- signed out -------------------------------------------------------------

def test_signed_out_is_200_with_null_user(client):
    """No cookie must not 401 — a red 401 on every cold open is exactly what
    the /auth/session probe was shaped to avoid, and /home inherits that."""
    r = client.get("/api/home")
    assert r.status_code == 200
    body = r.json()
    assert body["user"] is None
    assert body["businesses"] is None
    assert body["hero_audit"] is None


def test_garbage_cookie_is_200_with_null_user(client):
    client.cookies.set(settings.session_cookie_name, "not-a-token")
    r = client.get("/api/home")
    assert r.status_code == 200
    assert r.json()["user"] is None


# --- signed in --------------------------------------------------------------

def test_signed_in_no_businesses_returns_empty_list_not_null(client, db, make_user):
    """``[]`` and ``null`` mean different things to the frontend: empty list =
    'add your first business', null = 'you're signed out'. Conflating them
    sends a signed-in user to /login."""
    user = make_user(plan=UserPlan.free)
    _sign_in(client, db, user)

    body = client.get("/api/home").json()
    assert body["user"]["email"] == user.email
    assert body["businesses"] == []
    assert body["hero_audit"] is None


def test_user_payload_matches_auth_session(client, db, make_user):
    """The whole point of one payload is that it can't drift from the others."""
    user = make_user(plan=UserPlan.free)
    _sign_in(client, db, user)

    home = client.get("/api/home").json()
    session = client.get("/api/auth/session").json()
    assert home["user"] == session["user"]


def test_business_list_matches_businesses_endpoint(
    client, db, make_user, make_business, make_audit
):
    user = make_user(plan=UserPlan.free)
    biz = make_business(user, name="Kadai Coffee")
    make_audit(biz, sections=[(AuditSectionName.maps, 80)])
    db.commit()
    _sign_in(client, db, user)

    home = client.get("/api/home").json()
    listing = client.get("/api/businesses").json()
    assert home["businesses"] == listing


# --- hero audit -------------------------------------------------------------

def test_hero_audit_present_for_single_business(
    client, db, make_user, make_business, make_audit
):
    user = make_user(plan=UserPlan.free)
    biz = make_business(user, name="Kadai Coffee")
    audit = make_audit(biz, sections=[(AuditSectionName.maps, 80)])
    db.commit()
    _sign_in(client, db, user)

    body = client.get("/api/home").json()
    assert body["hero_audit"] is not None
    assert body["hero_audit"]["audit_id"] == audit.id


def test_hero_audit_matches_latest_audit_endpoint(
    client, db, make_user, make_business, make_audit
):
    user = make_user(plan=UserPlan.free)
    biz = make_business(user, name="Kadai Coffee")
    make_audit(biz, sections=[(AuditSectionName.maps, 80)])
    db.commit()
    _sign_in(client, db, user)

    home = client.get("/api/home").json()
    direct = client.get(f"/api/businesses/{biz.id}/latest-audit").json()
    assert home["hero_audit"] == direct


def test_no_hero_audit_when_multi_business(
    client, db, make_user, make_business, make_audit
):
    """Max accounts render the card grid, never the single-business hero — so
    sending the hero payload would be pure wasted bytes on the hot path."""
    user = make_user(plan=UserPlan.paid)
    first = make_business(user, name="Kadai Coffee")
    make_business(user, name="Kadai Two")
    make_audit(first, sections=[(AuditSectionName.maps, 80)])
    db.commit()
    _sign_in(client, db, user)

    body = client.get("/api/home").json()
    assert len(body["businesses"]) == 2
    assert body["hero_audit"] is None


def test_no_hero_audit_when_only_running_audit(
    client, db, make_user, make_business, make_audit
):
    """A first audit still in flight has no completed row to show."""
    user = make_user(plan=UserPlan.free)
    biz = make_business(user, name="Kadai Coffee")
    make_audit(biz, sections=[], status=AuditStatus.running)
    db.commit()
    _sign_in(client, db, user)

    body = client.get("/api/home").json()
    assert len(body["businesses"]) == 1
    assert body["hero_audit"] is None


def test_does_not_leak_another_users_business(
    client, db, make_user, make_business, make_audit
):
    owner = make_user(plan=UserPlan.free)
    other = make_user(plan=UserPlan.free)
    biz = make_business(other, name="Someone Else's")
    make_audit(biz, sections=[(AuditSectionName.maps, 90)])
    db.commit()
    _sign_in(client, db, owner)

    body = client.get("/api/home").json()
    assert body["businesses"] == []
    assert body["hero_audit"] is None
