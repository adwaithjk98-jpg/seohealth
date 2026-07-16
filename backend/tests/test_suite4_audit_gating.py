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

from app.models import Audit, AuditSection, Recommendation
from app.models.enums import RecommendationFixStatus
from app.services import audit_events
from app.services import audit_runner
from app.workers import queue as queue_mod
from app.workers.audit_jobs import run_audit_job
from scrapers.types import RecommendationDraft, SectionResult

from tests.conftest import AuditSectionName, AuditSectionStatus, AuditStatus


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


# --- 19 / 21 / 23 — driven through the real run_audit_job pipeline -----------
#
# These exercise decisions made *inside* ``audit_runner.run_audit`` (the spine
# gate, the non-spine soft-fail, the carry-forward of "done" marks), so we run
# the real state machine end to end with fake scrapers standing in for the
# network. What's stubbed is only the decoration the invariants don't depend on:
#   * the Redis event stream (no bus in unit tests),
#   * ``section_highlight`` (a live-feed headline; isolating it keeps a
#     decoration bug from masquerading as an audit failure here),
#   * ``prune_old_audit_data`` / score-change email / scheduled-done push
#     (opportunistic post-processing, each best-effort in prod).
# Everything load-bearing — ``_persist_section``, the Maps gate, the overall
# aggregation, ``_previous_done_titles`` — runs for real against this DB.


def _ok(score, recs=None):
    """A section scraper that succeeds with ``score`` (has a ``progress`` param
    so the runner calls it the same way it calls Maps/Website)."""

    async def _scraper(business_input, progress=None):
        return SectionResult(
            score=score, status="done", raw_data={}, recommendations=recs or []
        )

    return _scraper


def _raises(msg="scraper boom"):
    """A section scraper that dies — the runner's per-section ``except`` turns
    this into a score=None/failed row, the real network-failure shape."""

    async def _scraper(business_input, progress=None):
        raise RuntimeError(msg)

    return _scraper


def _ok_nap(score):
    """NAP has the odd two-positional signature (it takes prior sections'
    raw_data); the runner special-cases it, so match that shape."""

    async def _scraper(business_input, prior_raw=None):
        return SectionResult(score=score, status="done", raw_data={}, recommendations=[])

    return _scraper


def _install_pipeline(monkeypatch, db, pipeline):
    """Point the runner at a fake PIPELINE + this test's DB, and neutralise the
    decoration steps. run_audit opens its OWN session via the module-level
    ``SessionLocal`` name, so patch it on ``audit_runner`` (patching app.db
    wouldn't reach the already-imported reference)."""
    monkeypatch.setattr(audit_runner, "PIPELINE", pipeline)
    monkeypatch.setattr(audit_runner, "SessionLocal", sessionmaker(bind=db.bind))

    class _FakeStream:
        async def publish(self, event):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(
        audit_events, "get_or_create_stream", lambda audit_id: _FakeStream()
    )
    monkeypatch.setattr(audit_runner, "section_highlight", lambda *a, **k: None)
    monkeypatch.setattr(audit_runner, "prune_old_audit_data", lambda *a, **k: None)
    monkeypatch.setattr(audit_runner, "_maybe_notify_score_change", lambda *a, **k: None)
    monkeypatch.setattr(
        audit_runner, "_maybe_push_scheduled_audit_done", lambda *a, **k: None
    )


def test_19_maps_spine_failure_fails_audit(
    db, make_user, make_business, make_audit, monkeypatch
):
    """Maps (the spine) fails-to-measure → audit status='failed', not 'done',
    even though every other section succeeded. Guards the "confident score off
    one stub section" regression the gate was added for."""
    biz = make_business(make_user())
    audit = make_audit(biz, sections=[], status=AuditStatus.running)
    db.commit()  # the runner opens a separate session; make setup durable
    audit_id = audit.id

    _install_pipeline(
        monkeypatch,
        db,
        [
            (AuditSectionName.maps, _raises("Maps unreachable")),
            (AuditSectionName.website, _ok(70)),
            (AuditSectionName.performance, _ok(70)),
            (AuditSectionName.instagram, _ok(80)),
            (AuditSectionName.nap, _ok_nap(75)),
        ],
    )

    run_audit_job(audit_id)

    db.expire_all()
    refreshed = db.get(Audit, audit_id)
    assert refreshed.status == AuditStatus.failed
    # Pin the *gate* path specifically: the user-facing guidance, not a raw
    # exception repr from the outer catch-all (which would also fail the audit
    # but for a different reason and wouldn't prove the spine gate fired).
    assert "double-check the business name" in refreshed.error_message
    assert refreshed.finished_at is not None
    # The Maps row itself was persisted as failed (not silently absent).
    maps_row = (
        db.query(AuditSection)
        .filter_by(audit_id=audit_id, section=AuditSectionName.maps)
        .one()
    )
    assert maps_row.status == AuditSectionStatus.failed


def test_21_non_spine_failure_stays_done_with_none_section(
    db, make_user, make_business, make_audit, monkeypatch
):
    """A non-spine section (Website here) fails → the audit still completes
    'done', that section is score=None/failed, and the overall is the rounded
    mean of the *measured* sections — not dragged down by the gap."""
    biz = make_business(make_user())
    audit = make_audit(biz, sections=[], status=AuditStatus.running)
    db.commit()
    audit_id = audit.id

    _install_pipeline(
        monkeypatch,
        db,
        [
            (AuditSectionName.maps, _ok(88)),
            (AuditSectionName.website, _raises("PageSpeed/site timeout")),
            (AuditSectionName.performance, _ok(70)),
            (AuditSectionName.instagram, _ok(80)),
            (AuditSectionName.nap, _ok_nap(75)),
        ],
    )

    run_audit_job(audit_id)

    db.expire_all()
    refreshed = db.get(Audit, audit_id)
    assert refreshed.status == AuditStatus.done  # spine held → audit stands

    website_row = (
        db.query(AuditSection)
        .filter_by(audit_id=audit_id, section=AuditSectionName.website)
        .one()
    )
    assert website_row.score is None
    assert website_row.status == AuditSectionStatus.failed

    # Overall = round(mean(88, 70, 80, 75)) = round(78.25) = 78; the failed
    # website (None) is excluded, not counted as 0.
    scores = [
        s.score
        for s in db.query(AuditSection).filter_by(audit_id=audit_id)
        if s.score is not None
    ]
    from app.services.scoring import mean_or_none

    assert mean_or_none(scores) == 78


def test_23_carried_checkmarks_survive_failed_reaudit(
    db, make_user, make_business, make_audit, monkeypatch
):
    """A previous audit's 'done' check-mark must survive an infra-failed
    re-audit: the failed run re-persists the mark as done (not open), and the
    last-good audit that sources the carry-forward is left untouched — so a
    Maps outage never wipes the user's fix progress."""
    from datetime import datetime, timezone

    biz = make_business(make_user())

    # A prior COMPLETED audit with one recommendation the user marked done.
    prev = make_audit(
        biz,
        sections=[(AuditSectionName.website, 60)],
        status=AuditStatus.done,
        finished_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    done_rec = Recommendation(
        audit_id=prev.id,
        section=AuditSectionName.website,
        severity="high",
        title="Add your opening hours",
        body_markdown="…",
        fix_status=RecommendationFixStatus.done,
    )
    db.add(done_rec)
    db.commit()
    prev_id, prev_rec_id = prev.id, done_rec.id

    # The re-audit: Maps dies (spine failure → audit will fail), but Website
    # still runs and re-emits the same finding by title.
    reaudit = make_audit(biz, sections=[], status=AuditStatus.running)
    db.commit()
    reaudit_id = reaudit.id

    _install_pipeline(
        monkeypatch,
        db,
        [
            (AuditSectionName.maps, _raises("Maps unreachable")),
            (
                AuditSectionName.website,
                _ok(
                    0,
                    recs=[
                        RecommendationDraft(
                            severity="high",
                            title="Add your opening hours",
                            body_markdown="…",
                        )
                    ],
                ),
            ),
            (AuditSectionName.performance, _ok(70)),
            (AuditSectionName.instagram, _ok(80)),
            (AuditSectionName.nap, _ok_nap(75)),
        ],
    )

    run_audit_job(reaudit_id)

    db.expire_all()
    # The re-audit failed on the spine…
    assert db.get(Audit, reaudit_id).status == AuditStatus.failed
    # …yet the carried finding was persisted as DONE on the failed run, not
    # reset to open — the user's progress rode through the outage.
    carried = (
        db.query(Recommendation)
        .filter_by(audit_id=reaudit_id, title="Add your opening hours")
        .one()
    )
    assert carried.fix_status == RecommendationFixStatus.done
    assert carried.marked_done_at is not None
    # The last-good audit that sources the carry-forward is untouched…
    assert db.get(Recommendation, prev_rec_id).fix_status == RecommendationFixStatus.done
    # …and the chain still resolves to it (a failed re-audit is not 'done', so
    # it can never become the carry-forward source and sever the history).
    assert audit_runner._previous_done_titles(db, biz.id, reaudit_id) == {
        ("website", "Add your opening hours")
    }
    assert prev_id != reaudit_id  # sanity: two distinct audits in play
