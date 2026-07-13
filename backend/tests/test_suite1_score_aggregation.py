"""Suite 1 — overall-score aggregation (MONEY_TESTS_SPEC.md).

The invariant that keeps breaking: the composite overall is the mean of
sections whose ``score is not None`` (a measured 0 counts; status is never the
filter), opted-out pillars excluded, empty → None not 0. As of the closeout the
five inline copies were unified into ``services.scoring`` — these tests pin the
rule at the helper *and* through the real dashboard read path.
"""
from app.api.businesses import _audit_overall_score
from app.services.audit_runner import _previous_overall_score
from app.services.scoring import mean_or_none, overall_from_section_scores

from tests.conftest import (
    AuditSectionName as SEC,
    AuditSectionStatus as SECST,
    AuditStatus,
)

ALL = {"maps", "website", "instagram", "nap", "performance"}


# --- The six invariants, at the helper (spec tests 1–6) --------------------

def test_1_all_five_scored_is_mean():
    assert overall_from_section_scores(
        [("maps", 80), ("website", 90), ("instagram", 70), ("nap", 60), ("performance", 100)],
        ALL,
    ) == 80


def test_2_none_section_excluded_from_mean():
    # website unmeasurable → averaged over the other one only.
    assert overall_from_section_scores([("maps", 90), ("website", None)], ALL) == 90


def test_3_failed_zero_is_included_the_0s_but_85_regression():
    # A measured-bad 0 (status would be 'failed') MUST count. If a status-based
    # filter hid it, this would round up to 90 — the "0s but 85 overall" bug.
    assert overall_from_section_scores(
        [("maps", 90), ("website", 0), ("instagram", 0)], ALL
    ) == 30


def test_4_all_none_is_none_not_zero_not_crash():
    assert overall_from_section_scores([("maps", None), ("website", None)], ALL) is None


def test_5_opted_out_pillar_excluded():
    # website opted out → its 0 doesn't drag the average.
    assert overall_from_section_scores([("maps", 80), ("website", 0)], {"maps"}) == 80


def test_6_all_zero_is_zero_not_none():
    # 0 is a real measurement, distinct from "no data".
    assert overall_from_section_scores([("maps", 0), ("website", 0)], ALL) == 0


def test_mean_or_none_empty_is_none():
    assert mean_or_none([]) is None
    assert mean_or_none([50, 100]) == 75


# --- Through the real dashboard read path -----------------------------------

def test_dashboard_includes_failed_zero(make_user, make_business, make_audit):
    """The '0s but 85' regression, end-to-end through _audit_overall_score:
    a failed section persisted with score=0 is included."""
    user = make_user()
    biz = make_business(user)
    audit = make_audit(
        biz,
        sections=[
            (SEC.maps, 90, SECST.done),
            (SEC.website, 0, SECST.failed),   # measured bad
            (SEC.instagram, 0, SECST.failed),
        ],
    )
    # (90 + 0 + 0) / 3 = 30 — NOT 90.
    assert _audit_overall_score(audit, biz) == 30


def test_dashboard_excludes_opted_out_website(make_user, make_business, make_audit):
    user = make_user()
    biz = make_business(user, has_website=False)  # website + performance opt-out
    audit = make_audit(
        biz,
        sections=[
            (SEC.maps, 80, SECST.done),
            (SEC.website, 0, SECST.failed),        # opted out → excluded
            (SEC.performance, 0, SECST.failed),    # opted out → excluded
            (SEC.instagram, 70, SECST.done),
        ],
    )
    # Only maps(80) + instagram(70) count → 75.
    assert _audit_overall_score(audit, biz) == 75


def test_dashboard_all_unmeasurable_is_none(make_user, make_business, make_audit):
    user = make_user()
    biz = make_business(user)
    audit = make_audit(biz, sections=[(SEC.maps, None), (SEC.website, None)])
    assert _audit_overall_score(audit, biz) is None


def test_write_and_read_paths_agree(db, make_user, make_business, make_audit):
    """Unification proof: the runner's previous-overall (write path, feeds the
    score-change email) and the dashboard tile (read path) compute the SAME
    number for the same completed audit — including the opt-out rule that the
    write path used to omit."""
    user = make_user()
    biz = make_business(user, has_website=False)  # exercise the opt-out branch
    prev = make_audit(
        biz,
        sections=[
            (SEC.maps, 80, SECST.done),
            (SEC.website, 0, SECST.failed),   # opted out on both paths now
            (SEC.instagram, 70, SECST.done),
        ],
        status=AuditStatus.done,
    )
    # A later audit id so _previous_overall_score looks "before" it.
    current = make_audit(biz, sections=[(SEC.maps, 50, SECST.done)])

    dashboard = _audit_overall_score(prev, biz)
    from_email_path = _previous_overall_score(db, biz, current.id)
    assert dashboard == from_email_path == 75
