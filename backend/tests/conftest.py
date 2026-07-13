"""Shared pytest fixtures for the money-logic suite (MONEY_TESTS_SPEC.md).

Thin by design: an in-memory SQLite engine (schema built from the models — the
Postgres/Alembic drift check is a separate script), a ``db`` session rolled
back per test, and small factories. Only external HTTP (Places, Razorpay SDK)
ever gets monkeypatched; everything else is constructed for real.
"""
from __future__ import annotations

import itertools

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.models import Audit, AuditSection, Business, User
from app.models.base import Base
from app.models.enums import (
    AuditSectionName,
    AuditSectionStatus,
    AuditStatus,
    AuditTrigger,
    UserPlan,
)

_email_seq = itertools.count(1)


@pytest.fixture
def db():
    """A pristine in-memory DB per test.

    A fresh engine + schema each time is the simplest bulletproof isolation:
    the services under test call ``db.commit()`` freely (checkout, webhook,
    audit runner), and those commits just land in this test's throwaway
    database, discarded when the engine is disposed. Fast enough for the whole
    money suite to stay well under the 5s budget."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def make_user(db):
    def _make(plan: UserPlan = UserPlan.free, **kw) -> User:
        user = User(
            email=kw.pop("email", f"u{next(_email_seq)}@example.com"),
            plan=plan,
            **kw,
        )
        db.add(user)
        db.flush()
        return user

    return _make


@pytest.fixture
def make_business(db):
    def _make(user: User, **kw) -> Business:
        biz = Business(
            user_id=user.id,
            name=kw.pop("name", "Test Biz"),
            city=kw.pop("city", "Kochi"),
            country=kw.pop("country", "India"),
            **kw,
        )
        db.add(biz)
        db.flush()
        return biz

    return _make


@pytest.fixture
def make_audit(db):
    def _make(
        business: Business,
        sections: list | None = None,
        status: AuditStatus = AuditStatus.done,
        **kw,
    ) -> Audit:
        """``sections`` items are ``(AuditSectionName, score)`` or
        ``(AuditSectionName, score, AuditSectionStatus)``. A ``None`` score
        with no explicit status is treated as a failed/unmeasurable section."""
        audit = Audit(
            business_id=business.id,
            status=status,
            trigger=kw.pop("trigger", AuditTrigger.manual),
            **kw,
        )
        db.add(audit)
        db.flush()
        for spec in sections or []:
            name, score = spec[0], spec[1]
            if len(spec) > 2:
                sec_status = spec[2]
            else:
                sec_status = (
                    AuditSectionStatus.done
                    if score is not None
                    else AuditSectionStatus.failed
                )
            db.add(
                AuditSection(
                    audit_id=audit.id, section=name, score=score, status=sec_status
                )
            )
        db.flush()
        db.refresh(audit)
        return audit

    return _make


# Re-export enums so tests import one place.
__all__ = [
    "AuditSectionName",
    "AuditSectionStatus",
    "AuditStatus",
    "AuditTrigger",
    "UserPlan",
]
