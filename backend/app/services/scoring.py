"""Single source of truth for the audit *composite* overall score.

The overall a user sees — dashboard tile (`api/businesses`), glance header and
trend (`services/audit_view`), and the live-completion screen + score-change
email (`services/audit_runner`) — is the mean of that audit's per-section
scores. It was being recomputed inline in five places that had quietly drifted
apart on two points: the empty case (some returned ``0``, some ``None``) and
whether opted-out pillars were excluded (`_previous_overall_score` wasn't
excluding them, so the score-change email compared against a different rule
than the score it compared to). This module is the one place those rules live.

Invariants (memory ``feedback_overall_score_aggregation``):
* Average over sections whose ``score is not None``. A measured-bad ``0``
  counts; an unmeasurable ``None`` does not. **Status is never the filter** —
  filtering on ``status == 'failed'`` is the recurring "0s but 85 overall" bug.
* Opted-out pillars (FTUE questionnaire) drop out of the mean.
* No measurable + enabled section → ``None`` (unknown), never ``0``. Zero is a
  real measurement ("measured, and genuinely zero"); absence is not.
"""
from __future__ import annotations

from collections.abc import Iterable


def mean_or_none(scores: list[int]) -> int | None:
    """Rounded mean of already-filtered section scores, or ``None`` if empty.

    The combine half of the rule, shared by callers that have already applied
    the score-is-not-None + enabled filter inline (the read-path loops and the
    live runner both build such a list as they go)."""
    return round(sum(scores) / len(scores)) if scores else None


def overall_from_section_scores(
    section_scores: Iterable[tuple[str, int | None]],
    enabled: Iterable[str],
) -> int | None:
    """Overall from raw ``(section_name, score)`` pairs + the enabled pillar set.

    Applies both halves of the rule: keep sections whose ``score is not None``
    and whose pillar is ``enabled``, then :func:`mean_or_none`."""
    enabled_set = set(enabled)
    kept = [
        score
        for name, score in section_scores
        if score is not None and name in enabled_set
    ]
    return mean_or_none(kept)
