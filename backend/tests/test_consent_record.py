"""DPDP consent recording at signup.

Deliberately NOT named ``test_suite5_*``: the numbered suites map to
MONEY_TESTS_SPEC.md, and this is compliance logic, not money logic.

The rule under test is easy to break by accident and impossible to notice
once broken: consent is stamped exactly once, on the request that *creates*
the account. The signup form and the returning-login form are the same form
(anti-enumeration), so every returning sign-in also arrives with
``consent=True``. If that ever overwrote the stored timestamp, the record
would silently become "date of last login" and stop being evidence of
anything.
"""
from __future__ import annotations

from app.models import User
from app.services import auth as auth_service


def test_new_signup_with_consent_is_stamped(db):
    user, _ = auth_service.issue_magic_link(db, "new@example.com", consent=True)

    assert user.consent_at is not None
    assert user.consent_version == auth_service.CONSENT_VERSION


def test_new_signup_without_consent_records_nothing(db):
    """A client that didn't show the checkbox must not produce a consent record."""
    user, _ = auth_service.issue_magic_link(db, "quiet@example.com")

    assert user.consent_at is None
    assert user.consent_version is None


def test_returning_login_does_not_overwrite_the_original_consent(db):
    user, _ = auth_service.issue_magic_link(db, "repeat@example.com", consent=True)
    first_stamp = user.consent_at
    assert first_stamp is not None

    # Same form, same ticked box, days later.
    same_user, _ = auth_service.issue_magic_link(db, "repeat@example.com", consent=True)

    assert same_user.id == user.id
    assert same_user.consent_at == first_stamp, "consent_at drifted to last-login time"


def test_preexisting_user_is_not_backfilled(db):
    """Users who predate the checkbox stay NULL — we don't invent their consent."""
    legacy = User(email="legacy@example.com")
    db.add(legacy)
    db.flush()

    returned, _ = auth_service.issue_magic_link(db, "legacy@example.com", consent=True)

    assert returned.id == legacy.id
    assert returned.consent_at is None
    assert returned.consent_version is None
